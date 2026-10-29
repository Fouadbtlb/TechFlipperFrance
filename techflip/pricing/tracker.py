"""Local price tracker: per-component market value, learned from what we scrape.

Evidence, best first:
1. "owner": what you actually sold it for (config/sold.yaml). Already net,
   so appraise() applies no resale haircut on top.
2. "sold": single items that left the site (their last price) plus resale
   prices subscribers reported. The closest thing to real sales we can see.
3. "learned": median of single-item asking prices in the recency window.
4. "blend": asking median mixed with the seed while data is thin.
5. "seed": the catalog price, until anything better exists.

Only private sellers count: you resell as a private seller, and a shop's shelf
price (a Switch at 170 in a Cash Converters, 128 between individuals) would
invent margin on every listing.

Each quote also carries a low price (20th percentile, the realistic floor when
selling fast), how many days items took to go, and the subscribers' bounded
correction (+/-10 % at most, see Store.feedback_factor). A cheaper model is
never worth more than the model it is cut down from (Digital vs disc PS5).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from statistics import median, quantiles

from .extract import variant_rules


@dataclass(frozen=True)
class PriceQuote:
    key: str
    unit_value: float | None
    source: str  # owner | sold | learned | blend | seed | unknown
    n: int
    low: float | None = None           # realistic quick-sale floor
    days_to_sell: float | None = None  # median days on the market before it left
    crowd: float = 1.0                 # subscribers' correction applied


def _p20(values: list[float]) -> float:
    if len(values) < 2:
        return values[0]
    return quantiles(values, n=5, method="inclusive")[0]


def _cheaper_variants(catalog) -> dict[str, str]:
    """child key -> parent key, for variants the pricebook seeds below their
    parent (Digital under PS5, Lite under Switch; not OLED, which seeds above)."""
    out = {}
    for parent, children in variant_rules().items():
        p_seed = catalog.seed(parent)
        for child in children:
            c_seed = catalog.seed(child)
            if p_seed and c_seed and c_seed < p_seed:
                out[child] = parent
    return out


class PriceTracker:
    def __init__(self, store, catalog, min_comparables: int = 5, window_days: int = 90, *,
                 owner_sales: dict[str, float] | None = None, stale_days: float | None = None):
        self.store = store
        self.catalog = catalog
        self.min_comparables = min_comparables
        self.window_days = window_days
        self.owner_sales = owner_sales or {}
        # When set, asking prices of ads still online this many days after first
        # sighting are left out: they did not sell at that price. Used by the
        # shopping board; the scanner relies on "sold" evidence instead.
        self.stale_days = stale_days
        self._cheaper = _cheaper_variants(catalog)

    def price(self, key: str, exclude_uid: str | None = None) -> PriceQuote:
        q = self._price(key, exclude_uid)
        parent = self._cheaper.get(key)
        if parent and q.unit_value is not None:
            cap = self._price(parent, exclude_uid).unit_value
            if cap is not None and q.unit_value > cap:
                return replace(q, unit_value=cap, low=min(q.low, cap) if q.low else None)
        return q

    def _price(self, key: str, exclude_uid: str | None) -> PriceQuote:
        since = self._since()
        days = self.store.days_to_sell(key, since)
        dts = round(median(days), 1) if len(days) >= 3 else None
        if key in self.owner_sales:
            v = self.owner_sales[key]
            return PriceQuote(key, v, "owner", 0, low=v, days_to_sell=dts)

        seed = self.catalog.seed(key)
        band = (lambda p: 0.5 * seed <= p <= 2 * seed) if seed else (lambda p: True)
        sold = [p for p in self.store.sold_prices(key, since, exclude_uid) if p is not None and band(p)]
        asking = [p for p in self._asking(key, since, exclude_uid) if band(p)]
        crowd = self.store.feedback_factor(key, since)

        if len(sold) >= self.min_comparables:
            base, source, n, pool = median(sold), "sold", len(sold), sold
        elif not asking:
            return PriceQuote(key, seed, "seed" if seed is not None else "unknown", 0, days_to_sell=dts)
        elif len(asking) >= self.min_comparables or seed is None:
            base, source, n, pool = median(asking), "learned", len(asking), asking
        else:
            w = len(asking) / self.min_comparables
            base, source, n, pool = w * median(asking) + (1 - w) * seed, "blend", len(asking), None

        low = round(_p20(pool) * crowd, 2) if pool and len(pool) >= self.min_comparables else None
        return PriceQuote(key, round(base * crowd, 2), source, n, low, dts, crowd)

    def _asking(self, key: str, since: str, exclude_uid: str | None) -> list[float]:
        """Asking prices, without the ads that sat unsold when asked to. If every
        comparable has been sitting, a biased median still beats none."""
        if self.stale_days is not None:
            fresh = [p for p in self.store.component_prices(key, since, exclude_uid, self.stale_days)
                     if p is not None]
            if fresh:
                return fresh
        return [p for p in self.store.component_prices(key, since, exclude_uid) if p is not None]

    def _since(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()

    def drifted_seeds(self, tolerance: float = 0.18) -> list[dict]:
        """Seeds the scraped market disagrees with, worst first. A stale seed
        does more than bias one appraisal: the tracker only learns from ads
        within 0.5x-2x of the seed, so a seed far off filters out the very ads
        that would correct it."""
        since = self._since()
        out = []
        for d in self.catalog.defs:
            if not d.seed:
                continue
            prices = [p for p in self.store.component_prices(d.key, since)
                      if p is not None and 0.5 * d.seed <= p <= 2 * d.seed]
            if len(prices) < self.min_comparables:
                continue
            med = median(prices)
            drift = (med - d.seed) / d.seed
            if abs(drift) >= tolerance:
                out.append({"key": d.key, "label": d.label, "seed": d.seed,
                            "market": round(med, 2), "drift": round(drift, 3), "n": len(prices)})
        return sorted(out, key=lambda r: -abs(r["drift"]))
