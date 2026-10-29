"""Compose recognized components into a resale value.

true_value = sum(component value) * realization_factor, where each component is
priced by the tracker and discounted by a condition multiplier. Confidence is
the share of the value backed by learned (not seeded) prices, so a far/expensive
deal can be held to a higher bar than a cheap local one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..text import plain
from .extract import extract_components

# Categories where damage in the ad is damage to the item itself. For a part
# inside a bundle the wording may concern something else, so it only lowers
# confidence ("unknown").
CORE_CATEGORIES = {"console", "laptop", "monitor", "phone", "tablet"}
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
    "tablet": 0.85,
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
    # What it fetches even sold at the low end of recent comparables (None when
    # a part has too little data). "Au pire, il te reste..."
    floor_value: float | None = None
    # Days the main part usually stays online before it goes.
    days_to_sell: float | None = None


def listing_condition(llm_json: dict | None, text: str = "", title: str = "") -> str:
    """working | broken. The vision verdict wins when there is one; otherwise
    the ad's own words decide (`text`: title + description, `title` alone for
    the terse damage a shop writes only in titles)."""
    if llm_json:
        return "broken" if _is_broken(llm_json.get("condition")) else "working"
    t = plain(text)
    if any(not _negated(t, m.start()) for m in _DAMAGE.finditer(t)):
        return "broken"
    if _NAMED_DEFECT.search(t) or _TITLE_DAMAGE.search(plain(title)):
        return "broken"
    return "working"


# Damage wording in the three languages of the pool, matched on plain() text.
# Stems, because a shop writes "ABIMER" where a private seller writes "abime".
_DAMAGE = re.compile(r"""
      ne\ s'allume | ne\ fonctionne | en\ panne | hors\ service | pour\ pieces?
    | \bhs\b | defectueu\w* | \bdefect\w* | \bkapot\w* | beschadigd
    | \bcass(?:e|ee|es|ees)\b | \babim\w* | \bgebroken\b | court-circuit
    | \bfissur\w* | \bbarst\w* | \bgebarsten\b | schermprobleem
    | pixels?\ morts? | dode\ pixels? | pixels?\ dood | point\ vert
    | start\ niet\ op | werkt\ niet | gaat\ niet\ aan | moet\ (?:gemaakt|hersteld)
    | s'eteint | \ba\ changer\b | vendu\ (?:dans|en)\ l'etat
    | sans\ (?:la\ )?carte\ mere
    | \bblacklist\w* | bloque\ icloud | icloud\ bloque | verrouille\ icloud | activation\ lock
    | non\ officiel | (?:pas|non)\ d'origine | niet\ origineel
    | \bproblemes?\b | \bprobleem\b | \bproblemen\b
""", re.X)
# A word just before the damage, in the same clause, turns it into the
# commonest reassurance on the site: "sans fissure", "aucun pixel mort",
# "non blackliste", "geen barsten", "fonctionne sans probleme".
_NEGATIONS = frozenset({
    "sans", "aucun", "aucune", "pas", "ni", "non", "jamais", "rien", "zero", "0",
    "ne", "n", "geen", "zonder", "niet", "nooit", "no", "not", "never", "without"})
_CLAUSE = re.compile(r"[.,;:!?()\[\]/|+\n]")


def _negated(text: str, start: int) -> bool:
    clause = _CLAUSE.split(text[:start])[-1]
    return any(w in _NEGATIONS for w in re.findall(r"[0-9a-z]+", clause)[-3:])


# A pro shop names the defective part right after "etat": "(ETAT CHARNIERE)
# Z Fold 7", "(etat lentille)". "(Etat) 100 %" is condition plus battery.
_NAMED_DEFECT = re.compile(
    r"\betat\s+(?:charniere|lentille|ecran|scherm|dos|chassis|camera|vitre|coque"
    r"|batterie|clavier|lecteur)\b")
# Damage a shop writes in the TITLE only: in a description "coup de coeur" is
# everywhere, in a Cash Converters title "coup" is a dent.
_TITLE_DAMAGE = re.compile(r"\bcoups?\b|\blignes?\s+(?:sur\s+l'?)?ecran\b")


def build_items(text_components, llm_json, catalog, text: str = "", title: str = "") -> list[Item]:
    condition = listing_condition(llm_json, text, title)
    items: list[Item] = []
    console_family = None
    for comp in text_components:
        items.append(Item(comp.key, 1, _cond_for(comp.category, condition), comp.label, comp.category))
        if comp.category == "console":
            console_family = "xbox" if "xbox" in comp.key else "ps"
    if llm_json:
        items += _llm_extras(llm_json, catalog, console_family)
    return items


def appraise(items, tracker, realization_factor: float = 0.85,
             exclude_uid: str | None = None) -> Appraisal:
    """`exclude_uid`: the listing being valued, kept out of its own comparables."""
    gross = 0.0
    backed = 0.0
    net = 0.0
    lines: list[str] = []
    breakdown: list[dict] = []
    n_priced = 0
    n_unpriced = 0
    floor: float | None = 0.0
    main_val, main_days = -1.0, None
    for it in items:
        q = tracker.price(it.key, exclude_uid)
        if q.unit_value is None:
            n_unpriced += 1
            breakdown.append({"key": it.key, "label": it.label, "value": None, "source": "unknown"})
            floor = None
            continue
        mult = CONDITION_MULT.get(it.condition, 0.7)
        # A price you were actually paid is already net: no resale haircut on top.
        haircut = 1.0 if q.source == "owner" else REALIZATION.get(it.category, realization_factor)
        val = q.unit_value * it.qty * mult
        gross += val
        net += val * haircut
        n_priced += 1
        if q.source in ("owner", "sold", "learned", "blend"):
            backed += val
        if floor is not None:
            floor = None if q.low is None else floor + q.low * it.qty * mult * haircut
        if val > main_val:
            main_val, main_days = val, q.days_to_sell
        lines.append(_line(it, q, val))
        breakdown.append({
            "key": it.key, "label": it.label, "qty": it.qty, "condition": it.condition,
            "unit": q.unit_value, "value": round(val, 2), "source": q.source, "n": q.n,
            "low": q.low, "days_to_sell": q.days_to_sell,
        })
    true_value = round(net, 2)
    confidence = round(backed / gross, 2) if gross > 0 else 0.0
    floor_value = round(floor, 2) if floor and n_priced and not n_unpriced else None
    return Appraisal(true_value, round(gross, 2), confidence, tuple(lines),
                     tuple(breakdown), n_priced, n_unpriced, floor_value, main_days)


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
    tag = {"owner": "vendu par toi", "sold": "parties", "learned": "marché", "blend": "estim+",
           "seed": "estim"}.get(q.source, "?")
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
    # An ad the model itself types as a game or an accessory is not selling the
    # machine on its box art: a PSVR2 headset came back as "PS5 + 2 DualSense"
    # (444 EUR) and a sealed Tekken 8 as an Xbox Series X. Its type is ground truth.
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
# Ad types that can contain a whole machine. "other" and a missing type mean
# "could not tell", not "not a machine".
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
