"""Health and the RevenueCat webhook: endpoints called by machines."""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Header

from ... import tuning
from ..accounts import Accounts
from ..deps import ServicesDep, StoreDep, api_error
from ..entitlements import Entitlements

router = APIRouter(prefix="/v1", tags=["system"])


@router.get("/health")
def health(store: StoreDep):
    """`ok` is the API itself. `scanner` tells whether deals are still flowing:
    an uptime monitor should alert on scanner.stale, not only on HTTP errors."""
    beat = store.get_meta("scanner")
    scanner = {"last_cycle_at": None, "age_s": None, "stale": True, "last": None}
    if beat:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(beat["updated_at"])).total_seconds()
        scanner = {
            "last_cycle_at": beat["updated_at"],
            "age_s": round(age),
            "stale": age > tuning.SCANNER_STALE_AFTER.total_seconds(),
            "last": {k: v for k, v in beat.items() if k != "updated_at"},
        }
    return {"ok": True, "scanner": scanner}


@router.post("/webhooks/revenuecat")
def revenuecat_webhook(svc: ServicesDep, body: Annotated[dict, Body()],
                       authorization: Annotated[str, Header()] = ""):
    if not svc.api.revenuecat_webhook_auth:
        raise api_error(503, "webhook_not_configured")
    if not hmac.compare_digest(authorization.encode(), svc.api.revenuecat_webhook_auth.encode()):
        raise api_error(401, "unauthenticated")
    accounts = Accounts(svc.settings.db_path)
    try:
        ents = Entitlements(accounts, svc.api.revenuecat_secret_key, svc.api.revenuecat_entitlement, http=svc.http)
        touched = ents.handle_webhook(body)
    finally:
        accounts.close()
    return {"ok": True, "synced": len(touched)}
