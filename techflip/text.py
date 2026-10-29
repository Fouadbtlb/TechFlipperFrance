"""Text helpers shared by every rule that reads an ad.

Sellers write "écran", "ecran" and "ÉCRAN" for the same word, and type a
curly apostrophe as often as a straight one. Rules match against `plain()`
text so each word is listed once, without accents.
"""
from __future__ import annotations

import re
import unicodedata

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})


def plain(s: str | None) -> str:
    """Lowercase, accents stripped, apostrophes straightened."""
    s = unicodedata.normalize("NFD", (s or "").lower().translate(_APOSTROPHES))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def words(s: str | None) -> list[str]:
    """`plain()` text split into alphanumeric words."""
    return re.findall(r"[0-9a-z]+", plain(s))
