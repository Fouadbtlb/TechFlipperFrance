"""Compose recognized components into a resale value.

true_value = sum(component value) * realization_factor, where each component is
priced by the tracker and discounted by a condition multiplier. Confidence is
the share of the value backed by learned (not seeded) prices, so a far/expensive
deal can be held to a higher bar than a cheap local one.
"""
from __future__ import annotations

from dataclasses import dataclass

from .extract import extract_components

CORE_CATEGORIES = {"console", "laptop", "monitor"}
CONDITION_MULT = {"working": 1.0, "unknown": 0.7, "broken": 0.35}

# Asking-median -> realizable quick-flip haircut, per category. A used PSU sits
# and sells soft; a console clears near ask. The flat number was wrong at both
# tails. Items with no category fall back to the passed realization_factor.
REALIZATION = {
    "console": 0.92,
    "cpu": 0.90,
    "gpu": 0.85,
    "ram": 0.85,
    "storage": 0.85,
    "phone": 0.85,
    "controller": 0.85,
    "monitor": 0.82,
    "laptop": 0.80,
    "motherboard": 0.80,
    "game": 0.80,
    "psu": 0.70,
    "cooler": 0.70,
    "case": 0.65,
}


@dataclass(frozen=True)
class Item:
    key: str
    qty: int = 1
    condition: str = "working"
    label: str = ""
    category: str = ""


@dataclass(frozen=True)
class Appraisal:
    true_value: float
    gross_value: float
    confidence: float
    lines: tuple[str, ...]
    breakdown: tuple[dict, ...]
    n_priced: int
    n_unpriced: int


def listing_condition(llm_json: dict | None, text: str = "") -> str:
    if llm_json:
        c = str(llm_json.get("condition", "")).lower()
        if c.startswith("broken") or "hs" in c or "panne" in c:
            return "broken"
        return "working"
    tl = f" {text.lower()} "
    marks = ("ne s'allume", "en panne", "pour piece", "pour pièce", "hors service",
             "defectueux", "défectueux", " hs ", " hs,", " hs.", "cassé", "ne fonctionne")
    return "broken" if any(m in tl for m in marks) else "working"


def build_items(text_components, llm_json, catalog, text: str = "") -> list[Item]:
    condition = listing_condition(llm_json, text)
    items: list[Item] = []
    console_family = None
    for comp in text_components:
        items.append(Item(comp.key, 1, _cond_for(comp.category, condition), comp.label, comp.category))
        if comp.category == "console":
            console_family = "xbox" if "xbox" in comp.key else "ps"
    if llm_json:
        items += _llm_extras(llm_json, catalog, console_family)
    return items


def appraise(items, tracker, realization_factor: float = 0.85) -> Appraisal:
    gross = 0.0
    backed = 0.0
    net = 0.0
    lines: list[str] = []
    breakdown: list[dict] = []
    n_priced = 0
    n_unpriced = 0
    for it in items:
        q = tracker.price(it.key)
        if q.unit_value is None:
            n_unpriced += 1
            breakdown.append({"key": it.key, "label": it.label, "value": None, "source": "unknown"})
            continue
        mult = CONDITION_MULT.get(it.condition, 0.7)
        val = q.unit_value * it.qty * mult
        gross += val
        # A price the owner has actually been paid is already net. Applying
        # the resale haircut on top would discount the same money twice.
        net += val if q.source == "sold" else val * REALIZATION.get(
            it.category, realization_factor)
        n_priced += 1
        if q.source in ("learned", "blend", "sold"):
            backed += val
        lines.append(_line(it, q, val))
        breakdown.append({
            "key": it.key, "label": it.label, "qty": it.qty, "condition": it.condition,
            "unit": q.unit_value, "value": round(val, 2), "source": q.source, "n": q.n,
        })
    true_value = round(net, 2)
    confidence = round(backed / gross, 2) if gross > 0 else 0.0
    return Appraisal(true_value, round(gross, 2), confidence, tuple(lines),
                     tuple(breakdown), n_priced, n_unpriced)


def _cond_for(category: str, condition: str) -> str:
    if condition == "working":
        return "working"
    return condition if category in CORE_CATEGORIES else "unknown"


def _llm_extras(llm_json, catalog, console_family) -> list[Item]:
    out: list[Item] = []
    try:
        ctrl = int(llm_json.get("extra_controllers") or 0)
    except (TypeError, ValueError):
        ctrl = 0
    if ctrl > 0:
        key = "controller:xbox" if console_family == "xbox" else "controller:dualshock4"
        d = catalog.by_key.get(key)
        out.append(Item(key, ctrl, "working", d.label if d else "Manette", "controller"))
    storage = str(llm_json.get("extra_storage") or "").strip().lower()
    if storage and storage not in ("none", "non", "aucun"):
        sc = next((c for c in extract_components(storage, catalog) if c.category == "storage"), None)
        if sc:
            d = catalog.by_key.get(sc.key)
            out.append(Item(sc.key, 1, "working", d.label if d else "Stockage", "storage"))
    games = llm_json.get("notable_games") or []
    if isinstance(games, list) and games:
        out.append(Item("game:standard", len(games), "working", "Jeux", "game"))
    return out


def _line(it: Item, q, val: float) -> str:
    tag = {"learned": "marché", "blend": "estim+", "seed": "estim",
           "sold": "PRIX VENDU"}.get(q.source, "?")
    qty = f" x{it.qty}" if it.qty > 1 else ""
    cond = "" if it.condition == "working" else f" [{it.condition}]"
    return f"{it.label or it.key}{qty}{cond}: {val:.0f}€ ({tag})"



_LLM_TYPE_TO_CAT = {
    "gpu": "gpu", "cpu": "cpu", "ram": "ram", "storage": "storage", "psu": "psu",
    "motherboard": "motherboard", "console": "console", "controller": "controller",
    "game": "game", "monitor": "monitor",
}


def items_from_classification(verdict, catalog) -> list[Item]:
    """LLM classification -> items. Each component is canonicalized against the
    catalog, constrained to the LLM's type, so 'Manette PS5' -> controller, never
    console. The tracker still sets the euros."""
    cond = "broken" if _is_broken(verdict.get("condition")) else "working"
    raw = verdict.get("components")
    if not isinstance(raw, list):
        return []
    # An ad the model itself types as something other than a machine is not
    # selling a machine. It still lists one, because box art and marketing shots
    # show the console the thing plugs into or runs on: a PSVR2 headset came back
    # as "PS5 + 2 DualSense" and was valued at 444 EUR, and a sealed Tekken 8
    # came back as an Xbox Series X and alerted at +263 EUR while the very same
    # verdict put the item's resale at 50. Its own type field is ground truth.
    #
    # The first version of this guard only covered "accessory", which is why the
    # game got through; the rule is general now.
    barred = frozenset() if _is_machine_ad(verdict.get("type")) else _MACHINES
    items: list[Item] = []
    seen: set[str] = set()
    for comp in raw:
        if not isinstance(comp, dict):
            continue
        cat = _LLM_TYPE_TO_CAT.get(str(comp.get("type", "")).lower())
        if cat in barred:
            continue
        try:
            qty = max(1, int(comp.get("qty") or 1))
        except (TypeError, ValueError):
            qty = 1
        key = _canon(str(comp.get("model") or ""), cat, catalog)
        if key and key not in seen:
            seen.add(key)
            d = catalog.by_key[key]
            items.append(Item(key, qty, _cond_for(d.category, cond), d.label, d.category))
    return items


_MACHINES = frozenset({"console", "laptop"})

# Ad types that can legitimately contain a whole machine. "other" and a missing
# type are included on purpose: they mean "I could not tell", not "this is not a
# machine", and barring on a shrug would silence real ads.
_MACHINE_ADS = frozenset({"pc", "console", "laptop", "other", ""})


def _is_machine_ad(t) -> bool:
    return str(t or "").lower().strip() in _MACHINE_ADS


def _canon(model, cat, catalog):
    for c in extract_components(model, catalog):
        if cat is None or c.category == cat:
            return c.key
    return None


def _is_broken(c) -> bool:
    c = str(c or "").lower()
    return c.startswith("broken") or "hs" in c or "panne" in c
