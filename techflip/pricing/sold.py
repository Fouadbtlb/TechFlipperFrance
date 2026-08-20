"""Prices the owner has actually achieved.

Every other number in this tool is a median of ASKING prices, which is the
weakest evidence there is: overpriced ads never sell and keep voting forever,
correctly priced ones sell and leave. A real transaction price is the strongest
evidence there is, so it wins outright wherever it exists.

These are NET amounts -- what you receive -- so the realization haircut is not
applied on top of them. See `appraise`.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def load_sold(path: str | Path = "config/sold.yaml") -> dict[str, float]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, float] = {}
    for key, value in (raw.get("sold") or {}).items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out
