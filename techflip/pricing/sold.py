"""Prices the owner has actually achieved (config/sold.yaml).

Every other number in this tool comes from ASKING prices: overpriced ads never
sell and keep voting, correctly priced ones sell and leave. A real transaction
price is the strongest evidence there is, so it wins outright where it exists.

These are NET amounts, what you receive, so the resale haircut is not applied
on top of them. See `appraise`.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def load_sold(path: str | Path = "config/sold.yaml") -> dict[str, float]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, float] = {}
    for key, value in (raw.get("sold") or {}).items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out
