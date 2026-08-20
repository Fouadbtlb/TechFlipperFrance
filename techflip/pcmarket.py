"""What a complete tower actually sells for, keyed by the GPU inside it.

Valuing a PC as the sum of its parts is what kept every PC off this board. A
tower with an RTX 3060 asks a median of 700 EUR across 38 live listings; the
part sum for the same machine lands near 400. That gap is not an error in the
pricebook, it is a real premium: the buyer wants a machine that boots, with
Windows on it and nothing to assemble, and pays for it. Measured 2026-08-18
over 284 towers:

    GPU in the tower   n   median ask   GPU seed alone
    RTX 3060          38          700              260
    RTX 3070          11          999              320
    GTX 1060           7          279               60

So a build gets valued twice and keeps the better answer, which is exactly the
choice its buyer has: sell it whole, or strip it and sell the parts. Neither
number is authoritative on its own and the flipper takes the max of the two.

Both remain ASKING medians, so both are upper bounds. This lives on the board,
where a human reads every row, and stays out of the alert path.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict

from .pricing.extract import _is_bundle, recognize

# Undercut needed to actually shift a second-hand tower. Softer than parting out
# (one transaction, one buyer) but you never get the median you see listed.
PC_REALIZATION = 0.85

# The band that survives. Whole-tower asks are wildly dispersed for one GPU
# (an i3+3060 next to an i9+3060+64GB, plus the occasional 5300 EUR fantasy),
# so trim around a first-pass median before taking the real one.
_LO, _HI = 0.4, 2.5


class PCMarket:
    """Median asking price of complete towers, indexed by the GPU they contain.

    Built once per scan from the stored pool: ~300 recognitions, no network.
    """

    def __init__(self, min_comparables: int = 5):
        self._by_gpu: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self.min_comparables = min_comparables

    @classmethod
    def from_store(cls, store, catalog, min_comparables: int = 5) -> "PCMarket":
        m = cls(min_comparables)
        for row in store.all_listings():
            try:
                d = json.loads(row["raw_json"])
            except (ValueError, TypeError):
                continue
            m.add(d.get("title") or "", d.get("description") or "",
                  d.get("price"), f"{d.get('source')}:{d.get('source_id')}", catalog)
        return m

    def add(self, title, description, price, uid, catalog):
        if not price or price <= 0 or not _is_bundle(title):
            return
        low = f"{title} {description or ''}".lower()
        # A laptop is not a tower and its parts are not desktop parts. Letting
        # one into the pool drags the whole GPU tier toward retail laptop money.
        if any(w in low for w in ("portable", "laptop", "notebook", "macbook")):
            return
        gpu = next((c for c in recognize(title, description, catalog)
                    if c.category == "gpu"), None)
        if gpu:
            self._by_gpu[gpu.key].append((uid, float(price)))

    def median_ask(self, gpu_key: str, exclude_uid: str | None = None):
        """(median asking price, n) for towers with this GPU, or (None, n).

        The listing being valued is excluded from its own comparable set,
        otherwise a lone cheap tower partly justifies its own bargain.
        """
        prices = [p for uid, p in self._by_gpu.get(gpu_key, ()) if uid != exclude_uid]
        if len(prices) < self.min_comparables:
            return None, len(prices)
        rough = statistics.median(prices)
        kept = [p for p in prices if _LO * rough <= p <= _HI * rough]
        if len(kept) < self.min_comparables:
            return None, len(kept)
        return round(statistics.median(kept), 2), len(kept)

    def whole_value(self, gpu_key: str, exclude_uid: str | None = None):
        """Realizable price of the assembled machine, and how many ads back it."""
        med, n = self.median_ask(gpu_key, exclude_uid)
        if med is None:
            return None, n
        return round(med * PC_REALIZATION, 2), n
