"""Recognize catalog components inside a listing's text.

Cheap, text-only, no network. Runs on every listing at store time so the price
tracker can learn from single-item listings, and gives a first-pass component
list for appraisal. The LLM pass (deal candidates only) refines quantities and
condition on top of this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import Catalog


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    category: str
    qty: int = 1


def extract_components(text: str, catalog: Catalog) -> list[Component]:
    if not text:
        return []
    consumed: list[tuple[int, int]] = []
    out: list[Component] = []
    seen: set[str] = set()
    for d in catalog.ordered():
        span = _first_free_match(d.patterns, text, consumed)
        if span is None:
            continue
        consumed.append(span)
        if d.key not in seen:
            seen.add(d.key)
            out.append(Component(d.key, d.label, d.category))
    return out


# A machine has one GPU/CPU/motherboard/etc. A description that lists several
# is almost always marketing copy or comparisons ("mieux qu'une RTX 3050"), not
# real contents. So high-value categories are capped: trust the title, and drop
# them entirely when only the description mentions several.
_STRICT = {"gpu", "cpu", "motherboard", "laptop"}
_CAP1 = {"ram", "storage", "psu", "monitor"}
_TITLE_ONLY = {"console"}


_BUNDLE_TOKENS = {"pc", "tour", "setup", "ordinateur", "config", "lot",
                  "bundle", "unite", "unité", "combo", "pack"}


def is_bundle(title: str) -> bool:
    toks = set(re.split(r"[^0-9a-zà-ÿ]+", (title or "").lower()))
    return bool(toks & _BUNDLE_TOKENS)


_CONSOLE_WORDS = {"ps5", "ps4", "ps3", "playstation", "xbox", "switch", "console", "wii"}
_ACCESSORY_WORDS = {"manette", "manettes", "casque", "support", "telecommande",
                    "télécommande", "cable", "câble", "chargeur", "housse", "sacoche",
                    "socle", "station", "coque", "protection", "volant", "jeu", "jeux",
                    "simulateur", "pedales", "pédales", "pedalier",
                    "sticker", "stickers", "grip", "facade", "façade", "abonnement"}


def _console_is_subject(title: str) -> bool:
    toks = [t for t in re.split(r"[^0-9a-zà-ÿ]+", (title or "").lower()) if t]
    con = next((i for i, t in enumerate(toks) if t in _CONSOLE_WORDS), None)
    if con is None:
        return True
    acc = next((i for i, t in enumerate(toks) if t in _ACCESSORY_WORDS), None)
    return acc is None or con < acc


def recognize(title: str, description: str, catalog: Catalog) -> list[Component]:
    title_comps = extract_components(title or "", catalog)
    # Only a whole-machine/bundle listing absorbs parts named in its description.
    # A single-item sale ("RTX 4070 videokaart", "manette PS5") is valued on its
    # title alone, so context/compatibility mentions can't inflate it.
    if is_bundle(title):
        all_comps = extract_components(f"{title or ''} {description or ''}", catalog)
    else:
        all_comps = title_comps

    title_by_cat: dict[str, list[Component]] = {}
    for c in title_comps:
        title_by_cat.setdefault(c.category, []).append(c)
    all_by_cat: dict[str, list[Component]] = {}
    for c in all_comps:
        all_by_cat.setdefault(c.category, []).append(c)

    out: list[Component] = []
    for cat, comps in all_by_cat.items():
        title_comps_cat = title_by_cat.get(cat, [])
        if cat in _TITLE_ONLY:
            if title_comps_cat and _console_is_subject(title):
                out.append(title_comps_cat[0])
        elif cat in _STRICT:
            if title_comps_cat:
                out.append(title_comps_cat[0])
            elif len(comps) == 1:
                out.append(comps[0])
        elif cat in _CAP1:
            out.append(title_comps_cat[0] if title_comps_cat else comps[0])
        else:
            out.extend(comps)
    return out


def primary_key(components: list[Component]) -> str | None:
    """The key when the listing is a single recognized item, else None.

    Only single-item listings teach the tracker a clean per-component price.
    """
    return components[0].key if len(components) == 1 else None


def _first_free_match(patterns, text, consumed) -> tuple[int, int] | None:
    for rx in patterns:
        for m in rx.finditer(text):
            if not _overlaps(m.span(), consumed):
                return m.span()
    return None


def _overlaps(span, spans) -> bool:
    a, b = span
    return any(not (b <= x or a >= y) for x, y in spans)
