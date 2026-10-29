"""Pipeline: fetch -> ingest -> value -> alert the owner -> fan out to the app.

One cycle runs every configured search once. Feeder searches only teach the
price tracker; hunt searches are valued (valuation.py). A DataDome block stops
that one site for the cycle, the others carry on. Each cycle also re-checks a
few listings to learn what left the site (liveness.py), records a heartbeat for
/v1/health, and once a day prunes data nobody needs any more.

An owner alert is written off only once Telegram accepted it: a deal marked
"sent" after a failed send would never be seen.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import time
from collections.abc import Callable, Iterable

from lbc.exceptions import DatadomeError

from . import liveness
from .config import Settings
from .decision import policy_from_settings
from .domain import Listing, ScoreResult
from .geo import Locator
from .notify.telegram import TelegramNotifier
from .pricing.catalog import load_catalog
from .pricing.identify import components_of, teaching_key
from .pricing.sold import load_sold
from .pricing.tracker import PriceTracker
from .scoring.ai import AIVetter
from .sources.leboncoin import LeboncoinSource
from .storage import Store
from .valuation import Rejection, Valuation, Valuer
from .viewer import Viewer, judge

log = logging.getLogger(__name__)

_ZONE_MARK = {"EASY": "🟢", "MEDIUM": "🟠", "HARD": "🔴"}

# Called after each cycle; the app backend pushes deals to the subscribers
# they are a deal for (it looks at every recent deal, the list is a hint).
Fanout = Callable[[list[str]], None]


def _make_source(name: str, settings: Settings):
    if name == "leboncoin":
        return LeboncoinSource(proxy=settings.proxy, impersonate=settings.impersonate)
    if name == "2ememain":
        from .sources.deuxememain import DeuxiemeMainSource
        return DeuxiemeMainSource(proxy=settings.proxy)
    if name == "cashconverters":
        from .sources.cashconverters import CashConvertersSource
        return CashConvertersSource(proxy=settings.proxy)
    if name == "cashexpress":
        from .sources.cashexpress import CashExpressSource
        return CashExpressSource(proxy=settings.proxy)
    raise ValueError(f"source inconnue: {name!r}")


class Pipeline:
    def __init__(self, settings: Settings, fanout: Fanout | None = None,
                 origins: Callable[[], Iterable[tuple[float, float]]] | None = None):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.catalog = load_catalog(settings.pricebook_path)
        self.tracker = PriceTracker(self.store, self.catalog, settings.min_comparables, settings.window_days,
                                    owner_sales=load_sold(settings.sold_path))
        self.locator = Locator(origin=settings.home)
        self.policy = policy_from_settings(settings)
        self.owner = Viewer(home=settings.home, policy=self.policy, easy_km=settings.easy_km,
                            medium_km=settings.medium_km, cost_per_km=settings.cost_per_km)
        self.fanout = fanout
        self.sources = {}
        for s in settings.searches:
            self.sources.setdefault(s.source, _make_source(s.source, settings))
        self._searches = {s.name: s for s in settings.searches}
        vetter = AIVetter(settings.ai_url, settings.ai_model, settings.ai_max_images) if settings.ai_url else None
        self.valuer = Valuer(
            settings, self.store, self.catalog, self.tracker, self.locator, self.policy, self._searches,
            # Where the people who act on deals live: gates the expensive model calls.
            origins=origins or (lambda: [settings.home]),
            classify=vetter.classify if vetter else None,
            sellers=self._fetch_seller,
        )
        self.notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id)
        self._consecutive_errors = 0
        self._fresh: list[str] = []

    # ---------------------------------------------------------------- cycle

    def run_once(self) -> dict:
        stats = {"fetched": 0, "new": 0, "alerts": 0, "errors": 0}
        self._fresh = []
        blocked: set[str] = set()
        for search in self.settings.searches:
            if search.source in blocked:
                continue
            try:
                listings = self.sources[search.source].fetch(search)
                self._consecutive_errors = 0
            except DatadomeError:
                log.warning("DataDome block on %s, skipping %s for this cycle", search.name, search.source)
                stats["errors"] += 1
                self._consecutive_errors += 1
                blocked.add(search.source)
                continue
            except Exception:
                log.exception("fetch failed for %s", search.name)
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
        stats["departed"] = self._watch_departures()
        if self.fanout:
            try:
                self.fanout(list(dict.fromkeys(self._fresh)))
            except Exception:
                log.exception("fanout failed")
        self._housekeeping()
        self.store.set_meta("scanner", stats)
        log.info("cycle: %s | db: %s", stats, self.store.counts())
        return stats

    def _ingest(self, l: Listing):
        """Store the listing, pin it on the map, and record its primary component
        so the tracker learns a per-component price from single-item ads."""
        is_new = self.store.upsert_listing(l)
        if l.lat is None or l.lng is None:
            pos = self.locator.position(l.zipcode)
            if pos:
                self.store.set_position(l.uid, *pos)
        pk = teaching_key(l, self.catalog)
        self.store.set_primary_component(l.uid, pk, bool(pk))
        return is_new, components_of(l, self.catalog)

    def _resweep(self, days: int = 7) -> int:
        """Re-value recent listings as the tracker matures (cheap: the vision
        verdict is cached per price)."""
        since = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        n = 0
        for row in self.store.recent_unalerted(since):
            search = self._searches.get(row["search_name"])
            if search is None or search.kind != "hunt":
                continue
            l = Listing.from_dict(json.loads(row["raw_json"]))
            if self._evaluate(l, components_of(l, self.catalog)):
                n += 1
        if n:
            log.info("resweep: %d annonce(s) devenue(s) bonne(s) affaire(s)", n)
        return n

    def _evaluate(self, l: Listing, comps) -> bool:
        """Value one hunt listing and store the result. True if the owner was alerted."""
        if self.store.alert_tier(l.uid) == "confirmed":
            return False
        v = self.valuer.value(l, comps)
        if isinstance(v, Rejection):
            log.debug("%s rejected: %s", l.uid, v.reason)
            self.store.clear_appraisal(l.uid)
            if v.discard:
                self.store.mark_alerted(l.uid, None, None, tier="confirmed")
            return False
        self.store.save_appraisal(l.uid, true_value=v.true_value, price=l.price, confidence=v.confidence,
                                  category=v.category, appraisal=v.appraisal)
        if v.true_value > l.price:
            self._fresh.append(l.uid)
        return v.alertable and self._alert_owner(l, v)

    def _alert_owner(self, l: Listing, v: Valuation) -> bool:
        row = self.store.get(l.uid)
        j = judge(row, self.owner)
        self.store.update_owner_view(l.uid, j.net or 0.0, j.decision.zone, j.distance_km)
        if not j.alert:
            log.debug("no alert %s [%s]: %s", l.uid, j.decision.zone, j.decision.reasons)
            return False
        flags = (f"🚩 risque arnaque {int(v.risk)}/10",) if v.risk is not None and v.risk >= 6 else ()
        result = ScoreResult(listing_uid=l.uid, true_value=v.true_value, net_profit=j.net,
                             bundle_details=v.verdict or {}, reasons=flags)
        where = f"{j.distance_km:.0f}km de {self.settings.home_label}" if j.distance_km is not None \
            else "distance inconnue"
        mode = "envoi possible" if v.appraisal.get("shippable", True) else "retrait sur place"
        extra = [f"{_ZONE_MARK.get(j.decision.zone, '')} {j.decision.zone} · {where} · "
                 f"logistique {j.logistics:.0f}€ ({mode})",
                 f"Confiance {v.confidence:.0%} · {v.n_priced} pièce(s) valorisée(s)", *v.lines]
        if v.appraisal.get("photo_unverified"):
            extra.insert(0, "⚠️ photo non vérifiée, à contrôler sur place")
        if not self.notifier.send_deal(l, result, extra):
            log.warning("alert NOT delivered for %s, retried next cycle", l.uid)
            return False
        self.store.mark_alerted(l.uid, v.true_value, j.net, tier="confirmed")
        log.info("ALERT %s [%s] +%.0f€", l.uid, j.decision.zone, j.net)
        return True

    def _fetch_seller(self, l: Listing):
        fetch = getattr(self.sources.get(l.source), "fetch_seller", None)
        return fetch(l.seller_id) if fetch else None

    # ---------------------------------------------------------------- upkeep

    def _watch_departures(self) -> int:
        """Re-check a few listings per cycle (see liveness.py). One that left
        the site gives the tracker a near-sale price and a time to sell, and
        stops being shown as a deal."""
        budget = self.settings.departure_checks
        gone = 0
        for name, source in self.sources.items():
            if budget <= 0:
                break
            rows = self.store.due_for_check(budget, name)
            budget -= len(rows)
            gone += liveness.check(self.store, source, rows)["gone"]
        if gone:
            log.info("departures: %d annonce(s) partie(s)", gone)
        return gone

    def _housekeeping(self) -> None:
        """Once a day, drop what nothing reads any more (see Store.prune)."""
        last = self.store.get_meta("pruned")
        today = dt.date.today().isoformat()
        if last and last.get("day") == today:
            return
        removed = self.store.prune(keep_days=self.settings.window_days)
        self.store.set_meta("pruned", {"day": today, **removed})
        log.info("prune: %s", removed)

    # ---------------------------------------------------------------- warm-up and loop

    def bootstrap(self, pages: int = 3) -> int:
        total = 0
        blocked: set[str] = set()
        for search in self.settings.searches:
            if search.source in blocked:
                continue
            source = self.sources[search.source]
            for page in range(1, pages + 1):
                try:
                    listings = source.fetch(search, page=page)
                except DatadomeError:
                    log.warning("bootstrap: DataDome on %s, skipping %s", search.name, search.source)
                    blocked.add(search.source)
                    break
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

    def run_forever(self):
        log.info("starting loop: %d searches, poll %d-%ds", len(self.settings.searches),
                 self.settings.poll_seconds_min, self.settings.poll_seconds_max)
        if self.notifier.enabled:
            self.notifier.send_text("🟢 TechFlip démarré")
        while True:
            if self.settings.night_pause and _is_night():
                log.info("night pause; sleeping 30 min")
                time.sleep(1800)
                continue
            self.run_once()
            sleep = random.uniform(self.settings.poll_seconds_min, self.settings.poll_seconds_max)
            if self._consecutive_errors:
                sleep = min(3600, sleep * (2 ** self._consecutive_errors))
                log.warning("%d consecutive errors, backing off %.0fs", self._consecutive_errors, sleep)
            time.sleep(sleep)


def _is_night(now: dt.datetime | None = None) -> bool:
    t = (now or dt.datetime.now()).time()
    return dt.time(1, 0) <= t <= dt.time(6, 30)
