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

from .extract import _VARIANTS


@dataclass(frozen=True)
class PriceQuote:
    key: str
    unit_value: float | None
    source: str  # learned | blend | seed | unknown
    n: int


def _cheaper_variants(catalog) -> dict[str, str]:
    """child key -> parent key, for variants the pricebook seeds BELOW their parent.

    Derived from the recognizer's own variant map plus the seeds, so there is no
    second table to keep in sync. Only genuinely cheaper models are included: a
    Switch OLED is listed as a variant of a Switch but seeds above it, and must
    not be dragged down.
    """
    out = {}
    for parent, rules in _VARIANTS.items():
        p_seed = catalog.seed(parent)
        for _rx, child in rules:
            c_seed = catalog.seed(child)
            if p_seed and c_seed and c_seed < p_seed:
                out[child] = parent
    return out


class PriceTracker:
    def __init__(self, store, catalog, min_comparables: int = 5, window_days: int = 90,
                 stale_days: float | None = None, sold: dict | None = None):
        self.store = store
        self.catalog = catalog
        self.min_comparables = min_comparables
        self.window_days = window_days
        # When set, ads a search was still returning this many days after first
        # sighting are dropped from the median: they have not sold at that price,
        # so they are evidence about what sellers hope for, not about value.
        # Off by default -- the alert path keeps its old behaviour until this has
        # been judged on real data. See [tests/test_stale_price_bias.py].
        self.stale_days = stale_days
        # Prices the owner actually achieved. Strongest evidence available,
        # so it short-circuits the scraped median entirely. Already NET, so
        # `appraise` skips the realization haircut for this source.
        self.sold = sold or {}
        # A cut-down model may never be worth more than the model it is cut
        # down from. Pinning PS5 = 340 from a real sale while the Digital
        # kept its 345 asking median inverted the two.
        self._cheaper = _cheaper_variants(catalog)

    def price(self, key: str) -> PriceQuote:
        q = self._price(key)
        parent = self._cheaper.get(key)
        if parent and q.unit_value is not None:
            cap = self._price(parent).unit_value
            if cap is not None and q.unit_value > cap:
                return PriceQuote(key, cap, q.source, q.n)
        return q

    def _price(self, key: str) -> PriceQuote:
        if key in self.sold:
            return PriceQuote(key, self.sold[key], "sold", 0)
        seed = self.catalog.seed(key)
        since = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()
        prices = self._samples(key, since)
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

    def _samples(self, key: str, since: str) -> list[float]:
        """Comparables for one component, de-biased when asked.

        The filter yields rather than starving: if every comparable has been
        sitting, dropping them all would fall back to the seed and throw away
        the only market evidence there is. A biased median beats none.
        """
        if self.stale_days is None:
            return [p for p in self.store.component_prices(key, since) if p is not None]
        fresh = [p for p in self.store.component_prices(key, since, self.stale_days)
                 if p is not None]
        if fresh:
            return fresh
        return [p for p in self.store.component_prices(key, since) if p is not None]

    def drifted_seeds(self, tolerance: float = 0.18) -> list[dict]:
        """Seeds the scraped market disagrees with, worst first.

        A stale seed does more than bias one appraisal: `price` only learns from
        ads inside 0.5x-2x the seed, so a seed far from reality permanently
        filters out the very listings that would have corrected it.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()
        out = []
        for d in self.catalog.defs:
            if not d.seed:
                continue
            prices = [p for p in self.store.component_prices(d.key, since) if p is not None]
            prices = [p for p in prices if 0.5 * d.seed <= p <= 2 * d.seed]
            if len(prices) < self.min_comparables:
                continue
            med = median(prices)
            drift = (med - d.seed) / d.seed
            if abs(drift) >= tolerance:
                out.append({"key": d.key, "label": d.label, "seed": d.seed,
                            "market": round(med, 2), "drift": round(drift, 3),
                            "n": len(prices)})
        return sorted(out, key=lambda r: -abs(r["drift"]))
