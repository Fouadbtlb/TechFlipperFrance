"""The signed-in user: preferences, push token, subscription, deletion."""
from __future__ import annotations

import json

from fastapi import APIRouter

from ...geo import find_place
from ...notify.push import is_expo_token
from ..deps import AccountsDep, CurrentUser, EntitlementsDep, api_error
from ..entitlements import Entitlements
from ..schemas import PrefsIn, PushTokenIn

router = APIRouter(prefix="/v1/me", tags=["me"])


def me_payload(user, ents: Entitlements) -> dict:
    active = ents.is_active(user)
    return {
        "id": user["id"],
        "prefs": {
            "home_lat": user["home_lat"],
            "home_lng": user["home_lng"],
            "home_label": user["home_label"],
            "radius_km": user["radius_km"],
            "include_shipping": bool(user["include_shipping"]),
            "min_profit": user["min_profit"],
            "categories": json.loads(user["categories"] or "[]"),
            "notify": bool(user["notify"]),
            "notify_mode": user["notify_mode"] or "instant",
        },
        "entitlement": {
            "active": active,
            "until": user["entitled_until"] if active else None,
            "product": user["entitlement_product"] if active else None,
        },
    }


@router.get("/places")
def places(user: CurrentUser, q: str = ""):
    """Town or postcode -> coordinates, for clients without a geocoder (web)."""
    hit = find_place(q[:80])
    if hit is None:
        raise api_error(404, "place_not_found")
    # The same ~1 km rounding the app applies to a GPS fix.
    return {"lat": round(hit["lat"], 2), "lng": round(hit["lng"], 2), "label": hit["label"]}


@router.get("")
def me(user: CurrentUser, ents: EntitlementsDep):
    return me_payload(user, ents)


@router.patch("/prefs")
def update_prefs(body: PrefsIn, user: CurrentUser, accounts: AccountsDep, ents: EntitlementsDep):
    accounts.update_prefs(user["id"], body.model_dump(exclude_unset=True))
    return me_payload(accounts.user(user["id"]), ents)


@router.post("/push-token")
def push_token(body: PushTokenIn, user: CurrentUser, accounts: AccountsDep):
    if body.token is not None and not is_expo_token(body.token):
        raise api_error(400, "bad_push_token")
    accounts.set_push_token(user["id"], body.token)
    return {"ok": True}


@router.post("/entitlement/sync")
def sync_entitlement(user: CurrentUser, accounts: AccountsDep, ents: EntitlementsDep):
    """Called by the app right after a purchase or a restore."""
    ents.refresh(user["id"])
    return me_payload(accounts.user(user["id"]), ents)


@router.delete("")
def delete_me(user: CurrentUser, accounts: AccountsDep):
    accounts.delete_user(user["id"])
    return {"ok": True}
