"""Component catalog loaded from config/pricebook.yaml.

A catalog is a set of canonical components, each with match patterns and a seed
price. The extractor uses the patterns; the tracker uses the seed as a fallback
until it has learned a real market price.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ComponentDef:
    key: str
    label: str
    category: str
    seed: float | None
    ship_class: str
    patterns: tuple[re.Pattern, ...]
    specificity: int


class Catalog:
    def __init__(self, defs: list[ComponentDef]):
        self.defs = defs
        self.by_key = {d.key: d for d in defs}
        self._ordered = sorted(defs, key=lambda d: d.specificity, reverse=True)

    def ordered(self) -> list[ComponentDef]:
        """Most specific first, so 'rtx 4070 ti' wins over 'rtx 4070'."""
        return self._ordered

    def seed(self, key: str) -> float | None:
        d = self.by_key.get(key)
        return d.seed if d else None


def _pattern(alias: str) -> re.Pattern:
    tokens = alias.lower().split()
    body = r"\s*".join(re.escape(t) for t in tokens)
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


def load_catalog(path: str | Path = "config/pricebook.yaml") -> Catalog:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defs: list[ComponentDef] = []
    for item in raw.get("components", []):
        aliases = [str(item["label"]), *(str(a) for a in item.get("aliases", []))]
        specificity = max(len(a.split()) for a in aliases) * 100 + max(len(a) for a in aliases)
        defs.append(
            ComponentDef(
                key=item["key"],
                label=item["label"],
                category=item["category"],
                seed=item.get("seed"),
                ship_class=item.get("ship_class", "parcel"),
                patterns=tuple(_pattern(a) for a in aliases),
                specificity=specificity,
            )
        )
    return Catalog(defs)
