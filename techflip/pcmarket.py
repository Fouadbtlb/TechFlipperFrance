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
where a human reads every row, and stays out of the alert path. Only private
towers count (a shop's shelf price is not what you resell for), and never a
laptop, even one that hides it ("PC Gaming HP OMEN i7-13700HX RTX4080").
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict

from . import tuning
from .pricing.extract import is_bundle, recognize
from .pricing.identify import is_laptop, names_a_laptop

# Undercut needed to actually shift a second-hand tower. Softer than parting out
# (one transaction, one buyer) but you never get the median you see listed.
PC_REALIZATION = tuning.TOWER_REALIZATION

# The band that survives. Whole-tower asks are wildly dispersed for one GPU
# (an i3+3060 next to an i9+3060+64GB, plus the occasional 5300 EUR fantasy),
# so trim around a first-pass median before taking the real one.
_LO, _HI = 0.4, 2.5

# The CPU is half of what a buyer pays for. Keying comparables on the GPU alone
# priced a "GTX 1660 Super + i3-10100F" at 542 against i5 and i7 machines, and
# recommended it as the buy of the weekend at 300. Measured over the pool, the
# tier moves the price hard: RTX 3060 towers sit at 650 with an i5 and 1150
# with a Ryzen 9.
_TIER = re.compile(r"\b(i[3579]|ryzen\s*[3579]|celeron|pentium|athlon)\b", re.I)
_TIER_ALIAS = {"ryzen 3": "r3", "ryzen 5": "r5", "ryzen 7": "r7", "ryzen 9": "r9"}

# A comparable set whose middle half spans more than this fraction of its median
# is not an estimate, it is a coin flip. Calibrated against the real pools: the
# 1660 Super one (7 towers, 300-950) scores 0.50 and must be refused, while a
# genuine same-tier pool sits nearer 0.2. Refusing is the honest output, and
# the caller then falls back to the part sum.
_MAX_SPREAD = tuning.TOWER_MAX_SPREAD

# With no comparable at the same CPU tier, the build is somewhere in a pooled
# range and we do not know where. Take the low quarter rather than the middle:
# same posture as the unnamed-chassis credit, which uses the cheapest seed.
_FALLBACK_Q = 0.25


def cpu_tier(text: str) -> str | None:
    """i3 / i5 / i7 / i9 / r3..r9, or None when the ad never says."""
    m = _TIER.search(text or "")
    if not m:
        return None
    t = re.sub(r"\s+", " ", m.group(1).lower())
    return _TIER_ALIAS.get(t, t)


class PCMarket:
    """Median asking price of complete towers, indexed by the GPU they contain.

    Built once per scan from the stored pool: ~300 recognitions, no network.
    """

    def __init__(self, min_comparables: int = 5):
        self._by_gpu: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self._by_gpu_cpu: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
        self.min_comparables = min_comparables

    @classmethod
    def from_store(cls, store, catalog, min_comparables: int = 5) -> PCMarket:
        m = cls(min_comparables)
        for row in store.active_listings():
            try:
                d = json.loads(row["raw_json"])
            except (ValueError, TypeError):
                continue
            m.add(d.get("title") or "", d.get("description") or "", d.get("price"), row["uid"],
                  catalog, owner_type=row["owner_type"])
        return m

    def add(self, title, description, price, uid, catalog, owner_type: str | None = None):
        if not price or price <= 0 or owner_type == "pro" or not is_bundle(title):
            return
        comps = recognize(title, description, catalog)
        # A laptop is not a tower and its parts are not desktop parts. Letting
        # one into the pool drags the whole GPU tier toward retail laptop money.
        if names_a_laptop(title) or is_laptop(f"{title} {description or ''}", comps):
            return
        gpu = next((c for c in comps if c.category == "gpu"), None)
        if gpu:
            self._by_gpu[gpu.key].append((uid, float(price)))
            tier = cpu_tier(f"{title} {description or ''}")
            if tier:
                self._by_gpu_cpu[(gpu.key, tier)].append((uid, float(price)))

    def median_ask(self, gpu_key: str, exclude_uid: str | None = None,
                   cpu: str | None = None):
        """(price, n) for towers like this one, or (None, n) when unsure.

        Prefers comparables with the same CPU tier. Without them it falls back
        to the whole GPU pool but takes a low quartile rather than the median,
        because an unmatched build sits somewhere unknown in that range and
        guessing the middle is how an i3 machine inherited an i7 price.
        """
        same = [p for uid, p in self._by_gpu_cpu.get((gpu_key, cpu or ""), ())
                if uid != exclude_uid]
        if len(same) >= self.min_comparables:
            return self._robust(same, statistics.median)
        pooled = [p for uid, p in self._by_gpu.get(gpu_key, ()) if uid != exclude_uid]
        return self._robust(pooled, _quantile)

    def _robust(self, prices, pick):
        """Trim the fantasies, refuse the noise, then answer."""
        if len(prices) < self.min_comparables:
            return None, len(prices)
        rough = statistics.median(prices)
        kept = sorted(p for p in prices if _LO * rough <= p <= _HI * rough)
        if len(kept) < self.min_comparables:
            return None, len(kept)
        lo, hi = _quantile(kept, 0.25), _quantile(kept, 0.75)
        mid = statistics.median(kept)
        if mid <= 0 or (hi - lo) / mid > _MAX_SPREAD:
            return None, len(kept)
        return round(pick(kept), 2), len(kept)

    def whole_value(self, gpu_key: str, exclude_uid: str | None = None,
                    cpu: str | None = None):
        """Realizable price of the assembled machine, and how many ads back it."""
        med, n = self.median_ask(gpu_key, exclude_uid, cpu)
        if med is None:
            return None, n
        return round(med * PC_REALIZATION, 2), n


def _quantile(values, q: float = _FALLBACK_Q) -> float:
    """Simple order-statistic quantile; the samples are far too few for
    interpolation to mean anything."""
    xs = sorted(values)
    if not xs:
        return 0.0
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]
