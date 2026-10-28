"""What one listing is worth, independent of who looks at it.

    value(listing) = prefilter -> context -> text appraisal -> route ->
                     [vision check | whole-item estimate] -> finish

Each step either passes the work on or returns a Rejection saying why, so the
flow reads top to bottom and every exit is explicit. Who profits from the
result (distance, logistics, personal bar) is decided later, per viewer, in
viewer.judge().

Effort goes where it matters: every listing gets the cheap text appraisal;
only borderline, far, or easily faked candidates pay for the vision model,
and its verdict is cached per price.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .config import Settings
from .decision import ZonePolicy
from .domain import Listing
from .filters import price_prefilter, text_prefilter
from .geo import Locator, distance_km, logistics_cost, zone_for_distance
from .pricing.appraise import Appraisal, appraise, build_items, items_from_classification
from .pricing.catalog import Catalog
from .pricing.extract import is_bundle, primary_key
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
    "controller": "accessory", "game": "accessory",
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
        rejected = self._prefilter(l)
        if rejected:
            return rejected
        ctx = self._context(l, comps)
        if ctx is None:
            return Rejection("ni retrait ni envoi possible")

        text = f"{l.title} {l.description}"
        appr = self._appraise(build_items(comps, None, self.catalog, text), l)
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
        return self._with_seller(l, outcome)

    # ---------------------------------------------------------------- steps

    def _prefilter(self, l: Listing) -> Rejection | None:
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
        needs_photo = self._needs_photo(comps)
        wants_ai = needs_photo or ctx.zone != "EASY" or net < 1.5 * ctx.bar or appr.confidence < 0.5
        if not (self.classify and wants_ai):
            return self._result(appr, ctx, category, method="parts", verdict=None, risk=None)
        verdict = self.verdict(l)
        if verdict and verdict.get("is_trade") is True:
            return Rejection("échange, pas une vente", discard=True)
        if needs_photo:
            rejected = self._photo_matches_title(comps, verdict)
            if rejected:
                return rejected
        if verdict is None:
            return self._result(appr, ctx, category, method="parts", verdict=None, risk=None)
        items = items_from_classification(verdict, self.catalog) or build_items(comps, None, self.catalog, text)
        return self._result(self._appraise(items, l), ctx, category, method="parts+ai", verdict=verdict,
                            risk=_num(verdict.get("risque_arnaque")))

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
                alertable: bool = True) -> Valuation:
        appraisal = self._appraisal_dict(method=method, ctx=ctx, risk=risk, verdict=verdict,
                                         floor=appr.floor_value, days=appr.days_to_sell,
                                         n_priced=appr.n_priced, lines=appr.lines, breakdown=list(appr.breakdown))
        return Valuation(appr.true_value, appr.confidence, category, appraisal, appr.lines, appr.n_priced,
                         risk, verdict, alertable)

    @staticmethod
    def _appraisal_dict(*, method, ctx: _Context, risk, verdict, floor, days, n_priced, lines, breakdown) -> dict:
        return {
            "method": method, "breakdown": breakdown, "lines": list(lines), "risk": risk,
            "shippable": ctx.shippable, "ship_class": ctx.ship_class, "n_priced": n_priced,
            "photo_checked": verdict is not None, "floor": floor, "days_to_sell": days,
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

    def _photo_matches_title(self, comps, verdict) -> Rejection | None:
        """Fail closed: drop when the photos cannot be read, and discard for good
        when they show a different (usually cheaper) item than the title."""
        claimed = primary_key(comps)
        if not claimed:
            return None
        items = items_from_classification(verdict, self.catalog) if verdict else []
        category = self.catalog.by_key[claimed].category
        seen = next((i.key for i in items if i.category == category), None)
        if seen is None:
            return Rejection("photos illisibles pour confirmer le titre")
        if seen != claimed:
            return Rejection(f"photo: {seen} au lieu de {claimed}", discard=True)
        return None

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
