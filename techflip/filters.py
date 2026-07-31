"""Cheap prefilters, before any valuation work: price band + hard scam reject."""
from __future__ import annotations

import re
import unicodedata

from .domain import Listing


def text_prefilter(l: Listing, require: tuple[str, ...],
                   exclude: tuple[str, ...]) -> tuple[bool, str]:
    """A search's require (ALL must match) / exclude (NONE may match) regexes
    against title+description. This is what drops "recherche"/"achète" want-ads."""
    blob = f"{l.title} {l.description or ''}"
    for rx in exclude:
        if re.search(rx, blob, re.IGNORECASE):
            return False, f"exclu par /{rx}/"
    for rx in require:
        if not re.search(rx, blob, re.IGNORECASE):
            return False, f"manque /{rx}/"
    return True, "ok"


def price_prefilter(l: Listing, min_price: float, max_price: float | None,
                    max_eval_price: float) -> tuple[bool, str]:
    if l.price is None:
        return False, "prix absent"
    if l.price < min_price:
        return False, f"prix {l.price:.0f} < min {min_price:.0f}"
    if max_price is not None and l.price > max_price:
        return False, f"prix {l.price:.0f} > max {max_price:.0f}"
    if l.price > max_eval_price:
        return False, f"prix {l.price:.0f} > plafond {max_eval_price:.0f}"
    marker = scam_marker(l)
    if marker is not None:
        return False, f"signal verrouillage/arnaque: {marker}"
    return True, "ok"


# Listings never worth alerting on whatever the maths say: activation/account
# locks (phone or ex-corp laptop) and box/shell-only sold at product price. These
# are unambiguous phrases; carrier-unlock terms ("desimlocke", "debloque tout
# operateur") are deliberately NOT here since they say nothing about iCloud/FRP.
_SCAM_MARKERS = (
    "bloque icloud", "icloud bloque", "verrouille icloud",
    "verrouillage d activation", "activation lock",
    "compte google oublie", "frp lock",
    "mot de passe bios", "bios verrouille",
    "boite vide", "carton seul", "coque uniquement",
    "vends juste la boite", "juste le carton",
)


def scam_marker(l: Listing) -> str | None:
    blob = _norm(f"{l.title} {l.description or ''}")
    for m in _SCAM_MARKERS:
        if m in blob:
            return m
    return None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()
