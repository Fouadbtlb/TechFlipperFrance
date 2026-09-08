"""Pipeline: fetch -> ingest -> value -> alert.

One cycle runs every configured search once. Feeder searches only teach the
price tracker; hunt searches are appraised and can alert. The loop around it
adds human-ish pacing: jittered intervals, night pause, backoff on 403.

The valuation invests effort where it matters: every listing gets a cheap
text-only appraisal (which also feeds the tracker), and only borderline or far
deals get the slow local LLM/photo pass on top.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import time

from lbc.exceptions import DatadomeError

from .config import Settings
from .decision import ZonePolicy, decide
from .domain import Listing, ScoreResult
from .filters import price_prefilter, text_prefilter
from .geo import Locator, logistics_cost, zone_for_distance
from .hunt import _aisle_bars_machines, _MACHINE_CATEGORIES
from .notify.telegram import TelegramNotifier
from .pricing.appraise import appraise, build_items, items_from_classification
from .pricing.catalog import load_catalog
from .pricing.sold import load_sold
from .pricing.extract import (is_ambiguous_identity, primary_key, recognize,
                              teaches_price, _is_bundle)
from .pricing.tracker import PriceTracker
from .scoring.ai import AIVetter, _parse_verdict
from .sources.leboncoin import LeboncoinSource
from .storage import Store

log = logging.getLogger(__name__)

_ZONE_EMOJI = {"EASY": "🟢", "MEDIUM": "🟠", "HARD": "🔴"}
_NO_SHIP = ("main propre", "remise en main", "pas d'envoi", "pas de livraison",
            "aucun envoi", "sur place uniquement")
_SHIP_YES = ("envoi", "livraison", "mondial relay", "colissimo", "colis", "relais colis")


def _make_source(name: str, settings: Settings):
    if name == "leboncoin":
        return LeboncoinSource(impersonate=settings.impersonate)
    if name == "2ememain":
        from .sources.deuxememain import DeuxiemeMainSource
        return DeuxiemeMainSource()
    if name == "cashexpress":
        from .sources.cashexpress import CashExpressSource
        return CashExpressSource()
    if name == "cashconverters":
        from .sources.cashconverters import CashConvertersSource
        return CashConvertersSource()
    raise ValueError(f"source inconnue: {name!r}")


_VERIFY_CATS = {"console", "gpu", "laptop", "phone"}


def _needs_photo_verify(comps, catalog) -> bool:
    """A single liquid, easily-faked item must be eyeballed before it alerts."""
    k = primary_key(comps)
    if not k:
        return False
    d = catalog.by_key.get(k)
    return bool(d and d.category in _VERIFY_CATS)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.catalog = load_catalog(settings.pricebook_path)
        self.tracker = PriceTracker(
            self.store, self.catalog, settings.min_comparables, settings.window_days,
            sold=load_sold(settings.sold_path),
        )
        self.locator = Locator()
        self.policy = ZonePolicy(
            bars={"EASY": settings.easy_bar, "MEDIUM": settings.medium_bar, "HARD": settings.hard_bar},
            min_conf={"EASY": 0.0, "MEDIUM": settings.min_conf_medium, "HARD": settings.min_conf_hard},
        )
        self.sources = {}
        for s in settings.searches:
            if s.source not in self.sources:
                self.sources[s.source] = _make_source(s.source, settings)
        self.vetter = (
            AIVetter(settings.ai_url, settings.ai_model, settings.ai_max_images)
            if settings.ai_url else None
        )
        self.notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id)
        self._consecutive_errors = 0

    # ---------- one cycle ----------

    def run_once(self) -> dict:
        stats = {"fetched": 0, "new": 0, "alerts": 0, "errors": 0}
        blocked_sources: set[str] = set()
        for search in self.settings.searches:
            # A DataDome wall is per-source (Leboncoin), so skip the rest of that
            # source this cycle but keep polling the others (2ememain stays live).
            if search.source in blocked_sources:
                continue
            source = self.sources[search.source]
            try:
                listings = source.fetch(search)
                self._consecutive_errors = 0
            except DatadomeError:
                log.warning("DataDome block on %s — skipping source %s this cycle",
                            search.name, search.source)
                stats["errors"] += 1
                self._consecutive_errors += 1
                blocked_sources.add(search.source)
                continue
            except Exception:
                log.exception("Fetch failed for %s", search.name)
                stats["errors"] += 1
                self._consecutive_errors += 1
                continue

            stats["fetched"] += len(listings)
            for l in listings:
                is_new, comps = self._ingest(l)
                if is_new:
                    stats["new"] += 1
                    if search.kind == "hunt" and self._evaluate(l, comps):
                        stats["alerts"] += 1
            time.sleep(random.uniform(2.0, 6.0))

        stats["alerts"] += self._resweep()
        log.info("cycle: %s | db: %s", stats, self.store.counts())
        return stats

    def _ingest(self, l: Listing):
        """Store the listing and record its primary component so the tracker
        can learn a per-component price from single-item listings."""
        is_new = self.store.upsert_listing(l)
        comps = recognize(l.title, l.description, self.catalog)
        if _aisle_bars_machines(l.source_category):
            comps = [c for c in comps if c.category not in _MACHINE_CATEGORIES]
        clean = not _is_bundle(l.title) and teaches_price(l.title)
        pk = primary_key(comps) if clean else None
        self.store.set_primary_component(l.uid, pk, bool(pk))
        return is_new, comps

    def _resweep(self, days: int = 7) -> int:
        since = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        by_name = {s.name: s for s in self.settings.searches}
        n = 0
        for row in self.store.recent_unalerted(since):
            search = by_name.get(row["search_name"])
            if search is None or search.kind != "hunt":
                continue
            l = Listing.from_dict(json.loads(row["raw_json"]))
            comps = recognize(l.title, l.description, self.catalog)
            if self._evaluate(l, comps):
                n += 1
        if n:
            log.info("resweep: %d annonce(s) devenue(s) bonne(s) affaire(s)", n)
        return n

    # ---------- valuation + decision ----------

    def _evaluate(self, l: Listing, comps) -> bool:
        if self.store.alert_tier(l.uid) == "confirmed":
            return False
        if _aisle_bars_machines(l.source_category):
            comps = [c for c in comps if c.category not in _MACHINE_CATEGORIES]
        by_name = {s.name: s for s in self.settings.searches}
        search = by_name.get(l.search_name)
        min_price = search.min_price if search else 20
        max_price = search.max_price if search else None
        ok, why = price_prefilter(l, min_price, max_price, self.settings.max_eval_price)
        if not ok:
            log.debug("prefilter %s: %s", l.uid, why)
            return False
        if search:
            ok, why = text_prefilter(l, search.require, search.exclude)
            if not ok:
                log.debug("text prefilter %s: %s", l.uid, why)
                return False

        distance = self.locator.distance(l.zipcode, l.lat, l.lng)
        zone = zone_for_distance(distance, self.settings.easy_km, self.settings.medium_km)
        shippable = _is_shippable(l.description)
        ship_cls = _ship_class(comps, self.catalog)
        logistics = logistics_cost(distance, ship_cls, shippable, self.settings.cost_per_km)
        if logistics is None:
            return False
        bar = self.policy.bars[zone]

        appr = appraise(build_items(comps, None, self.catalog, f"{l.title} {l.description}"),
                        self.tracker, self.settings.realization_factor)
        net_text = appr.true_value - l.price - logistics
        true_value, confidence, lines, n_priced = (
            appr.true_value, appr.confidence, appr.lines, appr.n_priced)
        verdict = None
        risk = None
        photo_unverified = False

        decompose_deal = net_text >= 0.5 * bar
        # A single liquid, easily-faked item must be eyeballed on the photos before
        # it can alert: titles lie ("PS5" on a PS4 photo) and only the vision pass
        # catches that, so force the LLM here even for an easy high-confidence deal.
        needs_photo = _needs_photo_verify(comps, self.catalog)
        # near-Lille items the catalog can't decompose (laptops, phones, prebuilts):
        # let the LLM estimate a whole-item resale value instead of scoring them 0.
        whole_item = (self.vetter is not None and zone == "EASY"
                      and appr.n_priced == 0 and not decompose_deal)

        if decompose_deal:
            # Vision costs 20-60s of flat-out CPU per photo, which is what
            # heats the machine, so it is spent only where it changes a real
            # decision: a candidate already worth driving out for. Below that
            # margin the text appraisal stands on its own and the photo gate
            # simply reports "unverified".
            worth_a_look = net_text >= self.settings.ai_min_margin
            if self.vetter and worth_a_look and (
                    needs_photo or zone != "EASY"
                    or net_text < bar * 1.5 or appr.confidence < 0.5):
                verdict = self._run_llm(l)
            # The gate below runs whether or not a model exists. It used to be
            # nested inside `if self.vetter`, so configuring no AI at all did
            # not make the check fail closed, it removed the check: a bare
            # "Nintendo Switch" (very often the far cheaper Lite) alerted at
            # full console value. No model is the same evidence as a model that
            # is down -- none -- and has to reach the same "unverified" branch.
            # Load bearing now that the scanner runs with the vision pass off,
            # since CPU inference on photos is what heats the laptop.
            if needs_photo:
                status = self._verify_photo(l, comps, verdict)
                if status == "reject":
                    return False
                if status == "unverified":
                    # LLM down, absent, or blind: too far to inspect means drop;
                    # near Lille you go look in person, so alert with a warning
                    # rather than swallow the deal in silence. But an ambiguous
                    # model (a bare "Switch" that may be a cheap Lite) has no
                    # trustworthy value unverified, so it stays closed even near
                    # Lille -- no phantom-margin alert.
                    if zone != "EASY" or is_ambiguous_identity(comps, l.title):
                        return False
                    photo_unverified = True
            if verdict is not None:
                if verdict.get("is_trade") is True:
                    self.store.mark_alerted(l.uid, None, None, tier="confirmed")
                    return False
                risk = _num(verdict.get("risque_arnaque"))
                llm_items = items_from_classification(verdict, self.catalog)
                appr = appraise(
                    llm_items or build_items(comps, None, self.catalog,
                                             f"{l.title} {l.description}"),
                    self.tracker, self.settings.realization_factor)
                true_value, confidence, lines, n_priced = (
                    appr.true_value, appr.confidence, appr.lines, appr.n_priced)
        elif whole_item:
            verdict = self._run_llm(l)
            if not verdict or verdict.get("is_trade") is True:
                return False
            risk = _num(verdict.get("risque_arnaque"))
            llm_items = items_from_classification(verdict, self.catalog)
            if llm_items:
                appr = appraise(llm_items, self.tracker, self.settings.realization_factor)
                true_value, confidence, lines, n_priced = (
                    appr.true_value, appr.confidence, appr.lines, appr.n_priced)
            else:
                est = _num(verdict.get("valeur_revente_rapide"))
                if not est or est <= 0:
                    return False
                true_value = round(float(est) * self.settings.realization_factor, 2)
                confidence = 0.5
                lines = (f"Estimation IA a verifier: {est:.0f}€ revente occasion",)
                n_priced = 0
        else:
            return False

        d = decide(true_value, l.price, logistics, zone, confidence, self.policy, risk=risk)
        self.store.update_tech_score(
            l.uid, true_value, d.net_profit or 0.0, verdict or {"breakdown": list(appr.breakdown)},
            zone=zone, confidence=confidence, distance_km=distance,
        )
        if not d.alert:
            log.debug("no alert %s [%s]: %s", l.uid, zone, d.reasons)
            return False

        result = ScoreResult(
            listing_uid=l.uid, true_value=true_value, net_profit=d.net_profit,
            bundle_details=verdict or {}, reasons=_risk_flags(risk),
        )
        extra = _alert_extra(zone, distance, logistics, shippable, confidence, n_priced, lines)
        if photo_unverified:
            extra.insert(0, "⚠️ photo non vérifiée (IA indisponible), à contrôler sur place")
        # Only a delivered alert is written off. Marking on a failed send is how
        # a deal disappears without ever being seen: the next cycle skips it as
        # already-alerted. Left unmarked, the resweep retries it.
        if not self.notifier.send_deal(l, result, extra):
            log.warning("alert NOT delivered for %s — will retry next cycle", l.uid)
            return False
        self.store.mark_alerted(l.uid, true_value, d.net_profit, tier="confirmed")
        log.info("ALERT %s [%s] +%.0f€", l.uid, zone, d.net_profit)
        return True

    def _run_llm(self, l: Listing) -> dict | None:
        try:
            images = self.vetter._download_images(l.image_urls[: self.vetter.max_images])
            raw = self.vetter._chat(self.vetter._prompt(l, None, None), images)
            return _parse_verdict(raw)
        except Exception:
            log.warning("LLM failed on %s", l.uid, exc_info=True)
            return None

    def _verify_photo(self, l: Listing, comps, verdict) -> str:
        """Single liquid item (console/GPU/laptop/phone): confirm the photo shows
        what the title claims.
          'ok'         photos match the title (or nothing to verify), trust it.
          'reject'     photos show a different, usually cheaper item than
                       advertised ("PS5" on a PS4): confirmed bait, drop for good.
          'unverified' we could not run the vision check (LLM down) or it did not
                       recognise the item. Not proof of a lie, so the caller
                       keeps it near Lille (inspect in person) and drops it far."""
        claimed = primary_key(comps)
        if not claimed:
            return "ok"
        if not verdict:
            return "unverified"
        items = items_from_classification(verdict, self.catalog)
        cat = self.catalog.by_key[claimed].category
        seen = next((i.key for i in items if i.category == cat), None)
        if seen is None:
            return "unverified"
        if seen != claimed:
            self.store.mark_alerted(l.uid, None, None, tier="confirmed")
            return "reject"
        return "ok"

    # ---------- warm-up ----------

    def bootstrap(self, pages: int = 3) -> int:
        total = 0
        for search in self.settings.searches:
            source = self.sources[search.source]
            for page in range(1, pages + 1):
                try:
                    listings = source.fetch(search, page=page)
                except Exception:
                    log.exception("bootstrap: fetch failed (%s p%d)", search.name, page)
                    break
                if not listings:
                    break
                for l in listings:
                    self._ingest(l)
                total += len(listings)
                log.info("bootstrap %s p%d: %d annonces", search.name, page, len(listings))
                if len(listings) < 10:
                    break
                time.sleep(random.uniform(4.0, 9.0))
        return total

    # ---------- loop ----------

    def run_forever(self):
        log.info(
            "Starting loop: %d searches, poll %d-%ds",
            len(self.settings.searches),
            self.settings.poll_seconds_min,
            self.settings.poll_seconds_max,
        )
        if self.notifier.enabled:
            self.notifier.send_text("🟢 TechFlip démarré")

        while True:
            if self.settings.night_pause and _is_night():
                log.info("Night pause; sleeping 30 min")
                time.sleep(1800)
                continue

            self.run_once()

            sleep = random.uniform(
                self.settings.poll_seconds_min, self.settings.poll_seconds_max
            )
            if self._consecutive_errors:
                sleep = min(3600, sleep * (2 ** self._consecutive_errors))
                log.warning("%d consecutive errors → backing off %.0fs",
                            self._consecutive_errors, sleep)
            time.sleep(sleep)


def recompute_primary_components(store, catalog) -> dict:
    """Re-apply the current recognition rules to every stored listing.

    Rows keep whatever primary_component was derived when they were first seen,
    so a pool stays poisoned by ads ingested before a rule existed: bundles like
    "Xbox Series X + 2 manettes + 5 jeux" were still setting the price of a bare
    console long after the rule to exclude them landed. Only a re-fetch fixed
    those, and a listing that drops out of the search results never re-fetches.
    """
    import json as _json

    rows = store.conn.execute("SELECT uid, raw_json FROM listings").fetchall()
    stats = {"scanned": 0, "cleared": 0, "changed": 0}
    for r in rows:
        l = Listing.from_dict(_json.loads(r["raw_json"]))
        comps = recognize(l.title, l.description, catalog)
        clean = not _is_bundle(l.title) and teaches_price(l.title)
        pk = primary_key(comps) if clean else None
        old = store.conn.execute(
            "SELECT primary_component FROM listings WHERE uid=?", (r["uid"],)
        ).fetchone()["primary_component"]
        stats["scanned"] += 1
        if old != pk:
            store.set_primary_component(l.uid, pk, bool(pk))
            stats["cleared" if pk is None else "changed"] += 1
    return stats


def _is_shippable(desc: str | None) -> bool:
    d = (desc or "").lower()
    if any(p in d for p in _SHIP_YES):
        return True
    if any(p in d for p in _NO_SHIP):
        return False
    return True


def _ship_class(comps, catalog) -> str:
    if len(comps) >= 3:
        return "bulky"
    classes = [catalog.by_key[c.key].ship_class for c in comps if c.key in catalog.by_key]
    if "bulky" in classes:
        return "bulky"
    if "parcel" in classes:
        return "parcel"
    return classes[0] if classes else "parcel"


def _num(x) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def _risk_flags(risk) -> tuple[str, ...]:
    if isinstance(risk, (int, float)) and risk >= 6:
        return (f"🚩 risque arnaque {int(risk)}/10",)
    return ()


def _alert_extra(zone, distance, logistics, shippable, confidence, n_priced, lines) -> list[str]:
    dist_txt = f"{distance:.0f}km de Lille" if distance is not None else "distance inconnue"
    mode = "envoi possible" if shippable else "retrait sur place"
    out = [
        f"{_ZONE_EMOJI.get(zone, '')} {zone} · {dist_txt} · logistique {logistics:.0f}€ ({mode})",
        f"Confiance {confidence:.0%} · {n_priced} pièce(s) valorisée(s)",
    ]
    out += list(lines)
    return out


def _is_night(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    t = now.time()
    return t >= dt.time(1, 0) and t <= dt.time(6, 30)
