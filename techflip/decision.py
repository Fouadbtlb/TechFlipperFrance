"""Deal decision: net profit against a bar that gets stricter with distance.

EASY (near Lille) alerts on a thin margin because inspecting in person is cheap.
MEDIUM and HARD demand more profit AND more valuation confidence, and a far deal
with a scam signal is dropped rather than surfaced.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZonePolicy:
    bars: dict
    min_conf: dict


@dataclass(frozen=True)
class Decision:
    alert: bool
    net_profit: float | None
    zone: str
    bar: float
    reasons: tuple[str, ...]


def policy_from_settings(settings) -> ZonePolicy:
    """The house bars and confidence floors from the deployment settings."""
    return ZonePolicy(
        bars={"EASY": settings.easy_bar, "MEDIUM": settings.medium_bar, "HARD": settings.hard_bar},
        min_conf={"EASY": 0.0, "MEDIUM": settings.min_conf_medium, "HARD": settings.min_conf_hard},
    )


def default_policy() -> ZonePolicy:
    return ZonePolicy(
        bars={"EASY": 30.0, "MEDIUM": 80.0, "HARD": 120.0},
        min_conf={"EASY": 0.0, "MEDIUM": 0.4, "HARD": 0.6},
    )


def decide(true_value, price, logistics, zone, confidence, policy,
           risk=None, is_trade=False) -> Decision:
    bar = policy.bars[zone]
    min_conf = policy.min_conf[zone]

    if is_trade:
        return Decision(False, None, zone, bar, ("echange, pas un achat",))
    if logistics is None:
        return Decision(False, None, zone, bar, ("inaccessible (ni retrait ni envoi)",))
    if risk is not None and risk >= 8:
        return Decision(False, None, zone, bar, (f"risque arnaque {int(risk)}/10",))
    if risk is not None and risk >= 6 and zone != "EASY":
        return Decision(False, None, zone, bar, (f"risque arnaque {int(risk)}/10 a distance",))
    if price and true_value is not None and true_value > 3 * price:
        return Decision(False, None, zone, bar,
                        (f"valeur {true_value:.0f}€ irrealiste vs prix {price:.0f}€",))
    # Far item priced well under its value: a real seller offloads a bargain
    # locally in a day, so a cheap ship-only ad you can't inspect is almost always
    # a scam. Near Lille the same discount is a real deal (go check in person).
    if zone != "EASY" and price and true_value is not None and price < 0.6 * true_value:
        return Decision(False, None, zone, bar,
                        (f"prix {price:.0f}€ trop bas vs valeur {true_value:.0f}€ (arnaque à distance)",))

    net = round(true_value - price - logistics, 2)
    reasons = []
    if net < bar:
        reasons.append(f"marge {net:.0f}€ < seuil {bar:.0f}€ ({zone})")
    if confidence < min_conf:
        reasons.append(f"confiance {confidence:.0%} < {min_conf:.0%} ({zone})")
    alert = net >= bar and confidence >= min_conf
    return Decision(alert, net, zone, bar, tuple(reasons))
