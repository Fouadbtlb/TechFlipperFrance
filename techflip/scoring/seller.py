"""Seller trust assessment — pure logic, no network.

Input is a SellerInfo (or None when the profile fetch failed) plus the deal's
discount. Output is a list of human-readable lines for the alert message.
Lines starting with 🚩 are risk signals; the deeper the discount, the more a
young/empty account matters.
"""
from __future__ import annotations

import datetime as dt
import re

from ..domain import SellerInfo


def seller_lines(
    seller: SellerInfo | None,
    discount_pct: float | None,
    today: dt.date | None = None,
) -> list[str]:
    if seller is None:
        return ["⚠️ profil vendeur non vérifiable"]

    lines: list[str] = []
    discount = discount_pct or 0.0

    kind = {"private": "particulier", "pro": "pro"}.get(
        seller.account_type or "", seller.account_type or "?"
    )
    head = f"👤 {seller.name or 'vendeur'} ({kind})"

    age_days = _account_age_days(seller.registered_at, today)
    if age_days is not None:
        if age_days < 30:
            flag = "🚩" if discount >= 20 else "⚠️"
            lines.append(
                f"{flag} compte créé il y a {age_days} j"
                + (" + forte décote = pattern arnaque" if discount >= 20 else "")
            )
        else:
            years = age_days // 365
            head += f" · compte {years} an(s)" if years else f" · compte {age_days} j"

    if seller.feedback_score is not None and seller.feedback_count:
        head += f" · ⭐ {seller.feedback_score:.1f}/5 ({seller.feedback_count} avis)"
    elif (age_days or 0) >= 30:
        head += " · aucun avis"

    if seller.total_ads is not None and seller.total_ads <= 1 and discount >= 20:
        lines.append("⚠️ première annonce de ce vendeur")

    if seller.account_type == "pro" and discount >= 25:
        lines.append("⚠️ pro très sous le marché: vérifier (accident? import?)")

    return [head] + lines


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
    """Structured version of seller_lines() for the app. `flags` levels:
    "risk" (scam pattern) and "warn" (worth a question to the seller)."""
    if seller is None:
        return {"known": False, "flags": [{"level": "warn", "text": "Profil vendeur non vérifiable"}]}
    discount = discount_pct or 0.0
    age_days = _account_age_days(seller.registered_at, today)
    flags: list[dict] = []
    if age_days is not None and age_days < 30:
        if discount >= 20:
            flags.append({"level": "risk",
                          "text": f"Compte créé il y a {age_days} j et prix très bas"})
        else:
            flags.append({"level": "warn", "text": f"Compte créé il y a {age_days} j"})
    if seller.total_ads is not None and seller.total_ads <= 1 and discount >= 20:
        flags.append({"level": "warn", "text": "Première annonce de ce vendeur"})
    if seller.account_type == "pro" and discount >= 25:
        flags.append({"level": "warn", "text": "Pro très sous le marché, à vérifier"})
    return {
        "known": True,
        "name": seller.name,
        "kind": {"private": "particulier", "pro": "pro"}.get(seller.account_type or ""),
        "age_days": age_days,
        "rating": seller.feedback_score,
        "reviews": seller.feedback_count,
        "flags": flags,
    }
