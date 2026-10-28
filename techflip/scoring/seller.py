"""Seller trust assessment: pure logic, no network.

Input is a SellerInfo (or None when the profile fetch failed) plus the deal's
discount. The deeper the discount, the more a young or empty account matters:
a week-old account selling far under value is a scam pattern.
"""
from __future__ import annotations

import datetime as dt
import re

from ..domain import SellerInfo


def _account_age_days(
    registered_at: str | None, today: dt.date | None = None
) -> int | None:
    """Parse the source's date string leniently (ISO-ish prefix)."""
    if not registered_at:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", registered_at)
    if not m:
        return None
    today = today or dt.date.today()
    created = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return max(0, (today - created).days)


def seller_summary(
    seller: SellerInfo | None,
    discount_pct: float | None,
    today: dt.date | None = None,
) -> dict:
    """Seller trust for the app. `flags` levels:
    "risk" (scam pattern) and "warn" (worth a question to the seller)."""
    if seller is None:
        return {"known": False, "flags": [{"level": "warn", "text": "Profil vendeur non vérifiable"}]}
    discount = discount_pct or 0.0
    age_days = _account_age_days(seller.registered_at, today)
    flags: list[dict] = []
    if age_days is not None and age_days < 30:
        if discount >= 20:
            flags.append({"level": "risk",
                          "text": f"Compte créé il y a {age_days} jours, prix très bas"})
        else:
            flags.append({"level": "warn", "text": f"Compte créé il y a {age_days} jours"})
    if seller.total_ads is not None and seller.total_ads <= 1 and discount >= 20:
        flags.append({"level": "warn", "text": "Première annonce de ce vendeur"})
    if seller.account_type == "pro" and discount >= 25:
        flags.append({"level": "warn", "text": "Vendeur pro très en dessous du marché : à vérifier"})
    return {
        "known": True,
        "name": seller.name,
        "kind": {"private": "particulier", "pro": "pro"}.get(seller.account_type or ""),
        "age_days": age_days,
        "rating": seller.feedback_score,
        "reviews": seller.feedback_count,
        "flags": flags,
    }
