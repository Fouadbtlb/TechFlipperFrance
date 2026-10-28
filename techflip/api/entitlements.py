"""Subscription truth, decided server-side.

The app never tells us it is subscribed. RevenueCat validates the App Store /
Play receipts, and we ask RevenueCat directly with a SECRET key that never
ships in the app. A cracked client that flips `isPro = true` changes nothing:
every paid endpoint checks `entitled_until` here, which only this module writes.

Freshness: the webhook pushes renewals, cancellations, refunds and transfers
as they happen; a lazy re-check covers missed webhooks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from .accounts import Accounts

log = logging.getLogger(__name__)

RC_API = "https://api.revenuecat.com/v1"
FAR_FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)
RECHECK_AFTER = timedelta(hours=6)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def entitlement_until(subscriber: dict, entitlement: str) -> tuple[datetime | None, str | None]:
    """From a RevenueCat v1 subscriber payload: until when the entitlement is
    valid (grace period included), and the product granting it.
    `expires_date: null` means lifetime."""
    ent = ((subscriber or {}).get("entitlements") or {}).get(entitlement)
    if not ent:
        return None, None
    if ent.get("expires_date") is None:
        return FAR_FUTURE, ent.get("product_identifier")
    ends = [d for d in (_parse(ent.get("expires_date")),
                        _parse(ent.get("grace_period_expires_date"))) if d]
    return (max(ends) if ends else None), ent.get("product_identifier")


class Entitlements:
    def __init__(self, accounts: Accounts, secret_key: str, entitlement: str = "pro",
                 dev_unlock_all: bool = False, http: httpx.Client | None = None):
        self.accounts = accounts
        self.secret_key = secret_key
        self.entitlement = entitlement
        self.dev_unlock_all = dev_unlock_all
        self.http = http or httpx.Client(timeout=10)

    def is_active(self, user) -> bool:
        if self.dev_unlock_all:
            return True
        until = _parse(user["entitled_until"])
        now = datetime.now(timezone.utc)
        if until and until > now:
            return True
        # Expired or never subscribed: re-ask RevenueCat at most every few
        # hours, in case a renewal webhook was missed.
        checked = _parse(user["entitlement_checked_at"])
        if self.secret_key and (checked is None or now - checked > RECHECK_AFTER):
            until = self.refresh(user["id"])
            return bool(until and until > now)
        return False

    def refresh(self, user_id: str) -> datetime | None:
        """Re-fetch one user's entitlement from RevenueCat and store it."""
        if not self.secret_key:
            return None
        try:
            r = self.http.get(f"{RC_API}/subscribers/{quote(user_id, safe='')}",
                              headers={"Authorization": f"Bearer {self.secret_key}"})
            r.raise_for_status()
            sub = r.json().get("subscriber") or {}
        except Exception:
            log.warning("RevenueCat lookup failed for %s", user_id, exc_info=True)
            u = self.accounts.user(user_id)
            return _parse(u["entitled_until"]) if u else None
        until, product = entitlement_until(sub, self.entitlement)
        self.accounts.set_entitlement(user_id, until, product)
        return until

    def handle_webhook(self, body: dict) -> list[str]:
        """Re-sync every one of OUR users the event touches. Re-fetching instead
        of trusting the event payload is what RevenueCat recommends, and it makes
        retries and out-of-order delivery harmless."""
        ev = body.get("event") or {}
        ids: list[str] = [ev.get("app_user_id"), ev.get("original_app_user_id")]
        for key in ("aliases", "transferred_from", "transferred_to"):
            ids += list(ev.get(key) or [])
        touched = self.accounts.existing_user_ids(ids)
        for uid in touched:
            self.refresh(uid)
        return touched
