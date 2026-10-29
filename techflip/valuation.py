"""What one listing is worth, independent of who looks at it.

    value(listing) = prefilter -> context -> text appraisal -> route ->
                     [vision check | whole-item estimate] -> finish

Each step either passes the work on or returns a Rejection saying why, so the
flow reads top to bottom and every exit is explicit. Who profits from the
result (distance, logistics, personal bar) is decided later, per viewer, in
viewer.judge().

Effort goes where it matters: every listing gets the cheap text appraisal;
only borderline, far, or easily faked candidates worth AI_MIN_MARGIN pay for
the vision model, and its verdict is cached per price.

A single console, GPU, laptop or phone must have its photos checked against
its title. When that check cannot run (no model configured, model down, or
the item not recognized on the photos), the listing stays only near home,
flagged "photo non vérifiée" so you look in person, and never when the bare
title hides a cheaper model (a "Switch" is often a Lite).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from . import tuning
from .config import Settings
from .decision import ZonePolicy
from .domain import Listing
from .filters import not_an_offer, price_prefilter, text_prefilter
from .geo import Locator, distance_km, logistics_cost, zone_for_distance
from .pricing.appraise import Appraisal, appraise, build_items, items_from_classification
from .pricing.catalog import Catalog
from .pricing.extract import is_ambiguous_identity, is_bundle, primary_key
from .pricing.identify import carrier_locked
from .pricing.tracker import PriceTracker
from .scoring.seller import seller_summary
from .storage import Store

log = logging.getLogger(__name__)

# Catalog category -> the coarse category the app filters on.
APP_CATEGORY = {
    "console": "console", "gpu": "gpu", "cpu": "cpu", "laptop": "laptop",
    "phone": "phone", "monitor": "monitor",
    "ram": "parts", "storage": "parts", "psu": "parts", "motherboard": "parts",
    "cooler": "parts", "case": "parts",
    "controller": "accessory", "game": "accessory", "tablet": "phone",
}
_LLM_TYPE_CATEGORY = {"pc": "pc", "laptop": "laptop", "phone": "phone"}
# Single, liquid, easily faked items: the photos must confirm the title.
_VERIFY_CATS = {"console", "gpu", "laptop", "phone"}
_NO_SHIP = ("main propre", "remise en main", "pas d'envoi", "pas de livraison",
            "aucun envoi", "sur place uniquement")
_SHIP_YES = ("envoi", "livraison", "mondial relay", "colissimo", "colis", "relais colis")


@dataclass(frozen=True)
class Rejection:
    reason: str
    discard: bool = False   # True: never a deal (trade, bait photo), stop re-evaluating


@dataclass
class Valuation:
    true_value: float
    confidence: float
    category: str
    appraisal: dict                      # what gets stored and shown
    lines: tuple[str, ...] = ()
    n_priced: int = 0
    risk: float | None = None
    verdict: dict | None = None
    alertable: bool = True               # False: stored for later, not a candidate now
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Context:
    """Where the listing stands relative to the closest person who could act on it."""
    zone: str
    logistics: float
    bar: float
    shippable: bool
    ship_class: str


class Valuer:
    def __init__(self, settings: Settings, store: Store, catalog: Catalog, tracker: PriceTracker,
                 locator: Locator, policy: ZonePolicy, searches: dict,
                 origins: Callable[[], Iterable[tuple[float, float]]],
                 classify: Callable[[Listing], dict | None] | None = None,
                 sellers: Callable[[Listing], object] | None = None):
        self.settings = settings
        self.store = store
        self.catalog = catalog
        self.tracker = tracker
        self.locator = locator
        self.policy = policy
        self.searches = searches
        self.origins = origins
        # Vision model hook (None = no AI configured). Swappable in tests.
        self.classify = classify
        # Seller profile fetcher for a listing (None = not available).
        self.sellers = sellers

    # ---------------------------------------------------------------- flow

    def value(self, l: Listing, comps) -> Valuation | Rejection:
        rejected = self._prefilter(l, comps)
        if rejected:
            return rejected
        ctx = self._context(l, comps)
        if ctx is None:
            return Rejection("ni retrait ni envoi possible")

        text = f"{l.title} {l.description}"
        appr = self._appraise(build_items(comps, None, self.catalog, text, l.title), l)
        net = appr.true_value - l.price - ctx.logistics
        category = self._category(l, comps)

        if net >= 0.5 * ctx.bar:
            outcome = self._decomposed(l, comps, ctx, appr, net, text, category)
        elif self.classify and ctx.zone == "EASY" and appr.n_priced == 0:
            # Near items the catalog cannot decompose (laptops, phones, prebuilts):
            # let the model estimate a whole-item resale value instead of scoring 0.
            outcome = self._whole_item(l, ctx, appr, category)
        else:
            # Not a deal for anyone right now; keep the numbers so a maturing
            # tracker can flip it in a later resweep.
            return self._result(appr, ctx, category, method="parts", verdict=None, risk=None, alertable=False)
        if isinstance(outcome, Rejection):
            return outcome
        # Usable on one network only: still a phone, but not a clean resale.
        # Recorded so the app keeps it out of the reliable feed and says why.
        if category == "phone" and carrier_locked(text):
            outcome.appraisal["carrier_locked"] = True
        return self._with_seller(l, outcome)

    # ---------------------------------------------------------------- steps

    def _prefilter(self, l: Listing, comps) -> Rejection | None:
        why = not_an_offer(l, comps)
        if why:
            return Rejection(why, discard=True)
        search = self.searches.get(l.search_name)
        min_price = search.min_price if search else 20
        max_price = search.max_price if search else None
        ok, why = price_prefilter(l, min_price, max_price, self.settings.max_eval_price)
        if ok and search:
            ok, why = text_prefilter(l, search.require, search.exclude)
        return None if ok else Rejection(why)

    def _context(self, l: Listing, comps) -> _Context | None:
        pos = self.locator.position(l.zipcode, l.lat, l.lng)
        if pos and l.lat is None:
            self.store.set_position(l.uid, *pos)
        # Gate the expensive work on the closest person who could act on it.
        dists = [d for d in (distance_km(o, *pos) for o in self.origins()) if d is not None] if pos else []
        ref = min(dists) if dists else None
        zone = zone_for_distance(ref, self.settings.easy_km, self.settings.medium_km)
        shippable = is_shippable(l.description)
        ship_class = self._ship_class(comps)
        logistics = logistics_cost(ref, ship_class, shippable, self.settings.cost_per_km)
        if logistics is None:
            return None
        return _Context(zone, logistics, self.policy.bars[zone], shippable, ship_class)

    def _decomposed(self, l, comps, ctx: _Context, appr: Appraisal, net: float, text: str,
                    category: str) -> Valuation | Rejection:
        # A shop item is on a shelf under warranty: no fake-photo risk (tuning.SHOP_SOURCES).
        needs_photo = self._needs_photo(comps) and l.source not in tuning.SHOP_SOURCES
        wants_ai = needs_photo or ctx.zone != "EASY" or net < 1.5 * ctx.bar or appr.confidence < 0.5
        verdict = None
        if self.classify and wants_ai and net >= self.settings.ai_min_margin:
            verdict = self.verdict(l)
        if verdict and verdict.get("is_trade") is True:
            return Rejection("échange, pas une vente", discard=True)
        unverified = False
        if needs_photo:
            check = self._photo_matches_title(comps, verdict)
            if isinstance(check, Rejection):
                return check
            if check == "unverified":
                if ctx.zone != "EASY":
                    return Rejection("photo non vérifiée, trop loin pour aller voir")
                if is_ambiguous_identity(comps, l.title):
                    return Rejection("modèle ambigu sans vérification photo")
                unverified = True
        if verdict is None:
            return self._result(appr, ctx, category, method="parts", verdict=None, risk=None,
                                photo_unverified=unverified)
        items = (items_from_classification(verdict, self.catalog)
                 or build_items(comps, None, self.catalog, text, l.title))
        return self._result(self._appraise(items, l), ctx, category, method="parts+ai", verdict=verdict,
                            risk=_num(verdict.get("risque_arnaque")), photo_unverified=unverified)

    def _whole_item(self, l, ctx: _Context, appr: Appraisal, category: str) -> Valuation | Rejection:
        verdict = self.verdict(l)
        if not verdict:
            return Rejection("analyse IA indisponible")
        if verdict.get("is_trade") is True:
            return Rejection("échange, pas une vente", discard=True)
        risk = _num(verdict.get("risque_arnaque"))
        category = _LLM_TYPE_CATEGORY.get(str(verdict.get("type", "")).lower(), category)
        items = items_from_classification(verdict, self.catalog)
        if items:
            return self._result(self._appraise(items, l), ctx, category, method="parts+ai", verdict=verdict, risk=risk)
        est = _num(verdict.get("valeur_revente_rapide"))
        if not est or est <= 0:
            return Rejection("pas d'estimation IA")
        value = round(est * self.settings.realization_factor, 2)
        appraisal = self._appraisal_dict(
            method="ai", ctx=ctx, risk=risk, verdict=verdict, floor=None, days=None, n_priced=0,
            photo_unverified=False,
            lines=(f"Estimation IA a verifier: {est:.0f}€ revente occasion",),
            breakdown=[{"key": "ai:whole", "label": "Estimation IA (objet entier)", "qty": 1,
                        "value": value, "source": "ai", "n": 0}])
        return Valuation(value, 0.5, category, appraisal, appraisal["lines"], 0, risk, verdict)

    def _with_seller(self, l: Listing, v: Valuation) -> Valuation:
        """A young account selling far under value is a scam pattern: it raises
        the risk, which drops far deals in decide()."""
        if v.true_value <= l.price:
            return v
        seller = self._seller(l, v.true_value)
        v.appraisal["seller"] = seller
        if any(f["level"] == "risk" for f in seller.get("flags", [])):
            v.risk = max(v.risk or 0, 6.0)
            v.appraisal["risk"] = v.risk
        return v

    # ---------------------------------------------------------------- building blocks

    def _appraise(self, items, l: Listing) -> Appraisal:
        return appraise(items, self.tracker, self.settings.realization_factor, l.uid)

    def _result(self, appr: Appraisal, ctx: _Context, category: str, *, method: str, verdict, risk,
                alertable: bool = True, photo_unverified: bool = False) -> Valuation:
        appraisal = self._appraisal_dict(method=method, ctx=ctx, risk=risk, verdict=verdict,
                                         floor=appr.floor_value, days=appr.days_to_sell,
                                         n_priced=appr.n_priced, lines=appr.lines, breakdown=list(appr.breakdown),
                                         photo_unverified=photo_unverified)
        return Valuation(appr.true_value, appr.confidence, category, appraisal, appr.lines, appr.n_priced,
                         risk, verdict, alertable)

    @staticmethod
    def _appraisal_dict(*, method, ctx: _Context, risk, verdict, floor, days, n_priced, lines, breakdown,
                        photo_unverified) -> dict:
        return {
            "method": method, "breakdown": breakdown, "lines": list(lines), "risk": risk,
            "shippable": ctx.shippable, "ship_class": ctx.ship_class, "n_priced": n_priced,
            "photo_checked": verdict is not None, "photo_unverified": photo_unverified,
            "floor": floor, "days_to_sell": days,
        }

    def verdict(self, l: Listing) -> dict | None:
        """Vision verdict, cached per price: a resweep never pays twice."""
        cached = self.store.cached_verdict(l.uid, l.price)
        if cached is not None:
            return cached
        try:
            v = self.classify(l) if self.classify else None
        except Exception:
            log.warning("vision model failed on %s", l.uid, exc_info=True)
            v = None
        if v is not None:
            self.store.cache_verdict(l.uid, l.price, v)
        return v

    def _photo_matches_title(self, comps, verdict) -> Rejection | str:
        """"ok" when the photos show what the title claims (or there is nothing
        to check), "unverified" when no verdict could confirm it, and a
        Rejection, discarded for good, when they show a different (usually
        cheaper) item: "PS5" on a photo of a PS4."""
        claimed = primary_key(comps)
        if not claimed:
            return "ok"
        if not verdict:
            return "unverified"
        items = items_from_classification(verdict, self.catalog)
        category = self.catalog.by_key[claimed].category
        seen = next((i.key for i in items if i.category == category), None)
        if seen is None:
            return "unverified"
        if seen != claimed:
            return Rejection(f"photo: {seen} au lieu de {claimed}", discard=True)
        return "ok"

    def _needs_photo(self, comps) -> bool:
        key = primary_key(comps)
        d = self.catalog.by_key.get(key) if key else None
        return bool(d and d.category in _VERIFY_CATS)

    def _category(self, l: Listing, comps) -> str:
        if is_bundle(l.title) and len(comps) > 1:
            return "pc"
        if not comps:
            return "other"
        best = max(comps, key=lambda c: self.tracker.price(c.key).unit_value or 0)
        return APP_CATEGORY.get(best.category, "other")

    def _ship_class(self, comps) -> str:
        if len(comps) >= 3:
            return "bulky"
        classes = [self.catalog.by_key[c.key].ship_class for c in comps if c.key in self.catalog.by_key]
        for cls in ("bulky", "parcel"):
            if cls in classes:
                return cls
        return classes[0] if classes else "parcel"

    def _seller(self, l: Listing, true_value: float) -> dict:
        prev = self.store.get(l.uid)
        if prev and prev["appraisal"]:
            cached = json.loads(prev["appraisal"]).get("seller")
            if cached is not None:
                return cached
        if not (self.sellers and l.seller_id):
            return {"known": False, "flags": []}
        discount = max(0.0, (true_value - l.price) / true_value * 100) if true_value else 0.0
        return seller_summary(self.sellers(l), discount)


def is_shippable(desc: str | None) -> bool:
    d = (desc or "").lower()
    if any(p in d for p in _SHIP_YES):
        return True
    return not any(p in d for p in _NO_SHIP)


def _num(x) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None
