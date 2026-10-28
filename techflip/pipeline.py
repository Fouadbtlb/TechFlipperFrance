"""Pipeline: fetch -> ingest -> appraise -> fan out.

One cycle runs every configured search once. Feeder searches only teach the
price tracker; hunt searches are appraised. The appraisal (what a listing is
worth, how confident, how risky, does it ship) is location-independent and
stored once; who profits from it is decided per viewer in viewer.judge(), for
the owner's Telegram and for every app subscriber alike.

Effort goes where it matters: every listing gets a cheap text-only appraisal
(which also feeds the tracker), and only borderline, far, or easily-faked
candidates get the slow local LLM/photo pass. That verdict is cached per price,
so the resweep never pays for it twice.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import time
from typing import Callable, Iterable

from lbc.exceptions import DatadomeError

from .config import Settings
from .decision import ZonePolicy
from .domain import Listing, ScoreResult
from .filters import price_prefilter, text_prefilter
from .geo import Locator, distance_km, logistics_cost, zone_for_distance
from .notify.telegram import TelegramNotifier
from .pricing.appraise import appraise, build_items, items_from_classification
from .pricing.catalog import load_catalog
from .pricing.extract import primary_key, recognize, _is_bundle
from .pricing.tracker import PriceTracker
from .scoring.ai import AIVetter, _parse_verdict
from .scoring.seller import seller_summary
from .sources.leboncoin import LeboncoinSource
from .storage import Store
from .viewer import Viewer, judge

log = logging.getLogger(__name__)

_ZONE_EMOJI = {"EASY": "🟢", "MEDIUM": "🟠", "HARD": "🔴"}
_NO_SHIP = ("main propre", "remise en main", "pas d'envoi", "pas de livraison",
            "aucun envoi", "sur place uniquement")
_SHIP_YES = ("envoi", "livraison", "mondial relay", "colissimo", "colis", "relais colis")

# Catalog category -> the coarse category the app filters on.
APP_CATEGORY = {
    "console": "console", "gpu": "gpu", "cpu": "cpu", "laptop": "laptop",
    "phone": "phone", "monitor": "monitor",
    "ram": "parts", "storage": "parts", "psu": "parts", "motherboard": "parts",
    "cooler": "parts", "case": "parts",
    "controller": "accessory", "game": "accessory",
}
_LLM_TYPE_CATEGORY = {"pc": "pc", "laptop": "laptop", "phone": "phone"}


def _make_source(name: str, settings: Settings):
    if name == "leboncoin":
        return LeboncoinSource(impersonate=settings.impersonate)
    if name == "2ememain":
        from .sources.deuxememain import DeuxiemeMainSource
        return DeuxiemeMainSource()
    raise ValueError(f"source inconnue: {name!r}")


_VERIFY_CATS = {"console", "gpu", "laptop", "phone"}


def _needs_photo_verify(comps, catalog) -> bool:
    """A single liquid, easily-faked item must be eyeballed before it alerts."""
    k = primary_key(comps)
    if not k:
        return False
    d = catalog.by_key.get(k)
    return bool(d and d.category in _VERIFY_CATS)


# Called after each cycle with the uids appraised as positive-margin, so the
# app backend can push them to the subscribers they are a deal for.
Fanout = Callable[[list[str]], None]


class Pipeline:
    def __init__(self, settings: Settings, fanout: Fanout | None = None,
                 origins: Callable[[], Iterable[tuple[float, float]]] | None = None):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.catalog = load_catalog(settings.pricebook_path)
        self.tracker = PriceTracker(
            self.store, self.catalog, settings.min_comparables, settings.window_days
        )
        self.locator = Locator(origin=settings.home)
        self.policy = ZonePolicy(
            bars={"EASY": settings.easy_bar, "MEDIUM": settings.medium_bar, "HARD": settings.hard_bar},
            min_conf={"EASY": 0.0, "MEDIUM": settings.min_conf_medium, "HARD": settings.min_conf_hard},
        )
        self.owner = Viewer(home=settings.home, policy=self.policy, easy_km=settings.easy_km,
                            medium_km=settings.medium_km, cost_per_km=settings.cost_per_km)
        self.fanout = fanout
        # Where the people who will act on deals live. Gates the expensive LLM
        # work: an unrecognized laptop is only worth a model call if someone is
        # close enough to go and look at it.
        self.origins = origins or (lambda: [settings.home])
        self.sources = {}
        for s in settings.searches:
            if s.source not in self.sources:
                self.sources[s.source] = _make_source(s.source, settings)
        self.vetter = (
            AIVetter(settings.ai_url, settings.ai_model, settings.ai_max_images)
            if settings.ai_url else None
        )
        self.notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id)
        self._by_name = {s.name: s for s in settings.searches}
        self._consecutive_errors = 0
        self._fresh: list[str] = []

    # ---------- one cycle ----------

    def run_once(self) -> dict:
        stats = {"fetched": 0, "new": 0, "alerts": 0, "errors": 0}
        self._fresh = []
        for search in self.settings.searches:
            source = self.sources[search.source]
            try:
                listings = source.fetch(search)
                self._consecutive_errors = 0
            except DatadomeError:
                log.warning("DataDome block on %s, aborting cycle", search.name)
                stats["errors"] += 1
                self._consecutive_errors += 1
                break
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
        if self.fanout and self._fresh:
            try:
                self.fanout(list(dict.fromkeys(self._fresh)))
            except Exception:
                log.exception("fanout failed")
        log.info("cycle: %s | db: %s", stats, self.store.counts())
        return stats

    def _ingest(self, l: Listing):
        """Store the listing, pin it on the map, and record its primary component
        so the tracker can learn a per-component price from single-item ads."""
        is_new = self.store.upsert_listing(l)
        if l.lat is None or l.lng is None:
            pos = self.locator.position(l.zipcode)
            if pos:
                self.store.set_position(l.uid, *pos)
        comps = recognize(l.title, l.description, self.catalog)
        pk = None if _is_bundle(l.title) else primary_key(comps)
        self.store.set_primary_component(l.uid, pk, bool(pk))
        return is_new, comps

    def _resweep(self, days: int = 7) -> int:
        since = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        n = 0
        for row in self.store.recent_unalerted(since):
            search = self._by_name.get(row["search_name"])
            if search is None or search.kind != "hunt":
                continue
            l = Listing.from_dict(json.loads(row["raw_json"]))
            comps = recognize(l.title, l.description, self.catalog)
            if self._evaluate(l, comps):
                n += 1
        if n:
            log.info("resweep: %d annonce(s) devenue(s) bonne(s) affaire(s)", n)
        return n

    # ---------- valuation ----------

    def _evaluate(self, l: Listing, comps) -> bool:
        """Appraise one hunt listing, store it, and alert the owner if it is a
        deal for them. Returns True when the owner was alerted."""
        if self.store.alert_tier(l.uid) == "confirmed":
            return False
        search = self._by_name.get(l.search_name)
        min_price = search.min_price if search else 20
        max_price = search.max_price if search else None
        ok, why = price_prefilter(l, min_price, max_price, self.settings.max_eval_price)
        if ok and search:
            ok, why = text_prefilter(l, search.require, search.exclude)
        if not ok:
            log.debug("prefilter %s: %s", l.uid, why)
            self.store.clear_appraisal(l.uid)
            return False

        pos = self.locator.position(l.zipcode, l.lat, l.lng)
        if pos and l.lat is None:
            self.store.set_position(l.uid, *pos)
        # Gate the expensive work on the closest person who could act on it.
        ref_dist = self._nearest_origin_km(pos)
        ref_zone = zone_for_distance(ref_dist, self.settings.easy_km, self.settings.medium_km)
        shippable = _is_shippable(l.description)
        ship_cls = _ship_class(comps, self.catalog)
        ref_logistics = logistics_cost(ref_dist, ship_cls, shippable, self.settings.cost_per_km)
        if ref_logistics is None:
            self.store.clear_appraisal(l.uid)
            return False
        bar = self.policy.bars[ref_zone]
        text = f"{l.title} {l.description}"

        appr = appraise(build_items(comps, None, self.catalog, text),
                        self.tracker, self.settings.realization_factor, l.uid)
        net_text = appr.true_value - l.price - ref_logistics
        true_value, confidence, lines, n_priced = (
            appr.true_value, appr.confidence, appr.lines, appr.n_priced)
        breakdown = list(appr.breakdown)
        verdict = None
        risk = None
        method = "parts"
        category = self._category(l, comps)

        decompose_deal = net_text >= 0.5 * bar
        # A single liquid, easily-faked item must be eyeballed on the photos before
        # it can alert: titles lie ("PS5" on a PS4 photo) and only the vision pass
        # catches that, so force the LLM here even for an easy high-confidence deal.
        needs_photo = _needs_photo_verify(comps, self.catalog)
        # near items the catalog can't decompose (laptops, phones, prebuilts):
        # let the LLM estimate a whole-item resale value instead of scoring them 0.
        whole_item = (self.vetter is not None and ref_zone == "EASY"
                      and appr.n_priced == 0 and not decompose_deal)

        if decompose_deal:
            if self.vetter and (needs_photo or ref_zone != "EASY" or net_text < bar * 1.5
                                or appr.confidence < 0.5):
                verdict = self._verdict(l)
                if needs_photo and self._verify_photo(l, comps, verdict) == "reject":
                    return False
                if verdict is not None:
                    if verdict.get("is_trade") is True:
                        self._discard(l.uid)
                        return False
                    risk = _num(verdict.get("risque_arnaque"))
                    llm_items = items_from_classification(verdict, self.catalog)
                    appr = appraise(llm_items or build_items(comps, None, self.catalog, text),
                                    self.tracker, self.settings.realization_factor, l.uid)
                    true_value, confidence, lines, n_priced = (
                        appr.true_value, appr.confidence, appr.lines, appr.n_priced)
                    breakdown = list(appr.breakdown)
                    method = "parts+ai"
        elif whole_item:
            verdict = self._verdict(l)
            if not verdict or verdict.get("is_trade") is True:
                if verdict:
                    self._discard(l.uid)
                return False
            risk = _num(verdict.get("risque_arnaque"))
            category = _LLM_TYPE_CATEGORY.get(str(verdict.get("type", "")).lower(), category)
            llm_items = items_from_classification(verdict, self.catalog)
            if llm_items:
                appr = appraise(llm_items, self.tracker, self.settings.realization_factor, l.uid)
                true_value, confidence, lines, n_priced = (
                    appr.true_value, appr.confidence, appr.lines, appr.n_priced)
                breakdown = list(appr.breakdown)
                method = "parts+ai"
            else:
                est = _num(verdict.get("valeur_revente_rapide"))
                if not est or est <= 0:
                    self.store.clear_appraisal(l.uid)
                    return False
                true_value = round(float(est) * self.settings.realization_factor, 2)
                confidence = 0.5
                lines = (f"Estimation IA a verifier: {est:.0f}€ revente occasion",)
                breakdown = [{"key": "ai:whole", "label": "Estimation IA (objet entier)",
                              "qty": 1, "value": true_value, "source": "ai", "n": 0}]
                n_priced = 0
                method = "ai"
        else:
            # Not a deal for anyone right now; keep the numbers so a maturing
            # tracker can flip it in a later resweep.
            self._store(l, true_value, confidence, category, {
                "method": method, "breakdown": breakdown, "lines": list(lines),
                "risk": None, "shippable": shippable, "ship_class": ship_cls,
                "n_priced": n_priced})
            return False

        appraisal = {
            "method": method, "breakdown": breakdown, "lines": list(lines),
            "risk": risk, "shippable": shippable, "ship_class": ship_cls,
            "n_priced": n_priced,
            "photo_checked": verdict is not None,
        }
        if true_value > l.price:
            appraisal["seller"] = self._seller(l, true_value)
            if any(f["level"] == "risk" for f in appraisal["seller"].get("flags", [])):
                risk = max(risk or 0, 6.0)
                appraisal["risk"] = risk
        self._store(l, true_value, confidence, category, appraisal)
        return self._alert_owner(l, true_value, confidence, risk, verdict, lines, n_priced)

    def _store(self, l: Listing, true_value, confidence, category, appraisal):
        self.store.save_appraisal(l.uid, true_value=true_value, price=l.price,
                                  confidence=confidence, category=category,
                                  appraisal=appraisal)
        if true_value - l.price > 0:
            self._fresh.append(l.uid)

    def _alert_owner(self, l, true_value, confidence, risk, verdict, lines, n_priced) -> bool:
        row = self.store.get(l.uid)
        j = judge(row, self.owner)
        self.store.update_owner_view(l.uid, j.net or 0.0, j.decision.zone, j.distance_km)
        if not j.alert:
            log.debug("no alert %s [%s]: %s", l.uid, j.decision.zone, j.decision.reasons)
            return False
        result = ScoreResult(
            listing_uid=l.uid, true_value=true_value, net_profit=j.net,
            bundle_details=verdict or {}, reasons=_risk_flags(risk),
        )
        appr = json.loads(row["appraisal"])
        extra = _alert_extra(j.decision.zone, j.distance_km, j.logistics,
                             appr.get("shippable", True), confidence, n_priced, lines,
                             self.settings.home_label)
        self.notifier.send_deal(l, result, extra)
        self.store.mark_alerted(l.uid, true_value, j.net, tier="confirmed")
        log.info("ALERT %s [%s] +%.0f€", l.uid, j.decision.zone, j.net)
        return True

    def _discard(self, uid: str):
        """Never a deal (trade, bait photo): stop re-evaluating it."""
        self.store.clear_appraisal(uid)
        self.store.mark_alerted(uid, None, None, tier="confirmed")

    def _nearest_origin_km(self, pos) -> float | None:
        if pos is None:
            return None
        dists = [d for d in (distance_km(o, *pos) for o in self.origins()) if d is not None]
        return min(dists) if dists else None

    def _category(self, l: Listing, comps) -> str:
        if _is_bundle(l.title) and len(comps) > 1:
            return "pc"
        if not comps:
            return "other"
        best = max(comps, key=lambda c: self.tracker.price(c.key).unit_value or 0)
        return APP_CATEGORY.get(best.category, "other")

    def _seller(self, l: Listing, true_value: float) -> dict:
        prev = self.store.get(l.uid)
        if prev and prev["appraisal"]:
            cached = json.loads(prev["appraisal"]).get("seller")
            if cached is not None:
                return cached
        source = self.sources.get(l.source)
        fetch = getattr(source, "fetch_seller", None)
        if not (fetch and l.seller_id):
            return {"known": False, "flags": []}
        discount = max(0.0, (true_value - l.price) / true_value * 100) if true_value else 0.0
        return seller_summary(fetch(l.seller_id), discount)

    def _verdict(self, l: Listing) -> dict | None:
        cached = self.store.cached_verdict(l.uid, l.price)
        if cached is not None:
            return cached
        v = self._run_llm(l)
        if v is not None:
            self.store.cache_verdict(l.uid, l.price, v)
        return v

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
        what the title claims. 'reject' = drop, either because we could not read
        the item off the photos (fail closed) or because they show a different,
        usually cheaper item than advertised ("PS5" on a PS4). 'ok' = trust the
        verdict and revalue from it."""
        claimed = primary_key(comps)
        if not claimed:
            return "ok"
        items = items_from_classification(verdict, self.catalog) if verdict else []
        cat = self.catalog.by_key[claimed].category
        seen = next((i.key for i in items if i.category == cat), None)
        if seen is None:
            self.store.clear_appraisal(l.uid)
            return "reject"
        if seen != claimed:
            self._discard(l.uid)
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
                log.warning("%d consecutive errors, backing off %.0fs",
                            self._consecutive_errors, sleep)
            time.sleep(sleep)


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


def _alert_extra(zone, distance, logistics, shippable, confidence, n_priced, lines,
                 home_label: str = "Lille") -> list[str]:
    dist_txt = f"{distance:.0f}km de {home_label}" if distance is not None else "distance inconnue"
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
