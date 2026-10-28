"""Local price tracker: per-component market value, learned from what we scrape.

Evidence, best first:
1. "sold": single items that left the site (their last price) plus resale
   prices subscribers reported. The closest thing to real sales we can see.
2. "learned": median of single-item asking prices in the recency window.
3. "blend": asking median mixed with the seed while data is thin.
4. "seed": the catalog price, until anything better exists.

Each quote also carries a low price (20th percentile, the realistic floor when
selling fast), how many days items took to go, and the subscribers' bounded
correction (+/-10 % at most, see Store.feedback_factor).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median, quantiles


@dataclass(frozen=True)
class PriceQuote:
    key: str
    unit_value: float | None
    source: str  # sold | learned | blend | seed | unknown
    n: int
    low: float | None = None           # realistic quick-sale floor
    days_to_sell: float | None = None  # median days on the market before it left
    crowd: float = 1.0                 # subscribers' correction applied


def _p20(values: list[float]) -> float:
    if len(values) < 2:
        return values[0]
    return quantiles(values, n=5, method="inclusive")[0]


class PriceTracker:
    def __init__(self, store, catalog, min_comparables: int = 5, window_days: int = 90):
        self.store = store
        self.catalog = catalog
        self.min_comparables = min_comparables
        self.window_days = window_days

    def price(self, key: str, exclude_uid: str | None = None) -> PriceQuote:
        seed = self.catalog.seed(key)
        since = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()
        band = (lambda p: 0.5 * seed <= p <= 2 * seed) if seed else (lambda p: True)

        sold = [p for p in self.store.sold_prices(key, since, exclude_uid) if p is not None and band(p)]
        asking = [p for p in self.store.component_prices(key, since, exclude_uid) if p is not None and band(p)]
        days = self.store.days_to_sell(key, since)
        dts = round(median(days), 1) if len(days) >= 3 else None
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
