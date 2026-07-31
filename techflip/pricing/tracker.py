"""Local price tracker: per-component market value, learned from what we scrape.

For each canonical component it returns the seed price until enough real
single-item listings have been seen in the recency window, then the median of
those, blending across the threshold. This is autoscan's median-learning idea
keyed per component instead of per car model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median


@dataclass(frozen=True)
class PriceQuote:
    key: str
    unit_value: float | None
    source: str  # learned | blend | seed | unknown
    n: int


class PriceTracker:
    def __init__(self, store, catalog, min_comparables: int = 5, window_days: int = 90):
        self.store = store
        self.catalog = catalog
        self.min_comparables = min_comparables
        self.window_days = window_days

    def price(self, key: str) -> PriceQuote:
        seed = self.catalog.seed(key)
        since = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()
        prices = [p for p in self.store.component_prices(key, since) if p is not None]
        if seed:
            prices = [p for p in prices if 0.5 * seed <= p <= 2 * seed]
        n = len(prices)
        if n == 0:
            return PriceQuote(key, seed, "seed" if seed is not None else "unknown", 0)
        med = median(prices)
        if n >= self.min_comparables or seed is None:
            return PriceQuote(key, round(med, 2), "learned", n)
        w = n / self.min_comparables
        return PriceQuote(key, round(w * med + (1 - w) * seed, 2), "blend", n)
