"""Who profits from a deal: the per-viewer half of the decision.

A listing is appraised once (what it is worth, how sure we are, how risky it
looks, whether it ships). Whether it is a deal depends on who is looking: the
same PS5 is +90 EUR for someone 10 km away and a loss for someone who has to
ship it across France. `judge()` takes a stored appraisal and a Viewer (home,
personal bar, radius) and returns that viewer's decision.

The owner's Telegram alerts and every app subscriber go through this one path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .decision import Decision, ZonePolicy, decide
from .geo import distance_km, logistics_cost, zone_for_distance


@dataclass(frozen=True)
class Viewer:
    home: tuple[float, float]
    policy: ZonePolicy
    easy_km: float = 60
    medium_km: float = 150
    cost_per_km: float = 0.25
    radius_km: float | None = None       # None = no pickup limit
    include_shipping: bool = True        # far listings allowed when they ship
    categories: frozenset[str] = field(default_factory=frozenset)  # empty = all


@dataclass(frozen=True)
class Judgement:
    decision: Decision
    distance_km: float | None
    logistics: float | None
    mode: str            # "pickup" | "ship" | "none"
    visible: bool        # inside this viewer's radius / categories at all

    @property
    def alert(self) -> bool:
        return self.visible and self.decision.alert

    @property
    def net(self) -> float | None:
        return self.decision.net_profit


def policy_for(min_profit: float | None, defaults: ZonePolicy) -> ZonePolicy:
    """A viewer's own minimum profit raises the near bar; far bars never drop
    below the house defaults (shipping risk does not shrink because you want more
    deals)."""
    if min_profit is None:
        return defaults
    bars = {
        "EASY": float(min_profit),
        "MEDIUM": max(float(min_profit), defaults.bars["MEDIUM"]),
        "HARD": max(float(min_profit), defaults.bars["HARD"]),
    }
    return ZonePolicy(bars=bars, min_conf=defaults.min_conf)


def judge(row, viewer: Viewer) -> Judgement:
    """`row` is a listings row (sqlite Row or dict) with a stored appraisal."""
    appr = _appraisal(row)
    price = row["price"]
    true_value = row["true_value"]
    dist = distance_km(viewer.home, row["lat"], row["lng"])
    zone = zone_for_distance(dist, viewer.easy_km, viewer.medium_km)
    shippable = bool(appr.get("shippable", True))
    ship_class = appr.get("ship_class", "parcel")

    in_radius = viewer.radius_km is None or (dist is not None and dist <= viewer.radius_km)
    can_ship = viewer.include_shipping and shippable
    in_categories = not viewer.categories or (row["category"] in viewer.categories)
    visible = in_categories and (in_radius or can_ship)

    # Outside the pickup radius, the viewer is not going to drive there.
    logistics = logistics_cost(dist if in_radius else None, ship_class,
                               shippable and viewer.include_shipping, viewer.cost_per_km)
    mode = _mode(dist if in_radius else None, ship_class, shippable and viewer.include_shipping,
                 viewer.cost_per_km, logistics)

    d = decide(true_value, price, logistics, zone, row["confidence"] or 0.0, viewer.policy,
               risk=appr.get("risk"), is_trade=bool(appr.get("is_trade")))
    return Judgement(d, dist, logistics, mode, visible)


def _mode(dist, ship_class, shippable, cost_per_km, logistics) -> str:
    if logistics is None:
        return "none"
    if dist is not None and round(2 * dist * cost_per_km, 2) == logistics:
        return "pickup"
    return "ship" if shippable else "pickup"


def _appraisal(row) -> dict:
    raw = row["appraisal"]
    if not raw:
        return {}
    return raw if isinstance(raw, dict) else json.loads(raw)
