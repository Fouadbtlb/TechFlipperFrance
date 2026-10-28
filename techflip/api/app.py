"""TechFlip app backend.

Security model (details in docs/SECURITY.md):
1. All value stays on the server: the scanner, the pricebook, the tracker,
   the valuations. The app is a viewer with nothing worth cracking.
2. Only a genuine app on a genuine device gets an account: App Attest (iOS)
   or Play Integrity (Android) at registration AND at every token refresh.
3. Only paying users get data: every deal endpoint checks the entitlement
   that RevenueCat verified against Apple/Google, server-side.
4. Stolen tokens die fast: 15 min access JWTs; refresh tokens rotate, are
   single-use, device-bound, and reuse revokes the whole session.
5. Scraping a paid account is bounded: per-user rate and daily caps.
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import jwt
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ..config import ApiSettings, Settings
from ..storage import Store
from .accounts import Accounts, TokenReuse
from .attest import AppleAppAttest, AttestationError, PlayIntegrity
from .deals import CATEGORIES, SORTS, card, deals_for, detail, pin, sort_deals, teaser, viewer_for
from .entitlements import Entitlements
from ..notify.push import is_expo_token
from ..viewer import judge

log = logging.getLogger(__name__)

ISSUER = "techflip"


# ---------------------------------------------------------------- models

class RegisterIn(BaseModel):
    platform: Literal["ios", "android", "dev"]
    challenge: str = Field(max_length=200)
    key_id: str | None = Field(default=None, max_length=200)          # iOS
    attestation: str | None = Field(default=None, max_length=20000)   # iOS
    integrity_token: str | None = Field(default=None, max_length=20000)  # Android


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)
    challenge: str = Field(max_length=200)
    assertion: str | None = Field(default=None, max_length=5000)
    integrity_token: str | None = Field(default=None, max_length=20000)


class PrefsIn(BaseModel):
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)
    home_label: str | None = Field(default=None, max_length=80)
    radius_km: float | None = Field(default=None, ge=5, le=1000)
    include_shipping: bool | None = None
    min_profit: float | None = Field(default=None, ge=0, le=5000)
    categories: list[str] | None = None
    notify: bool | None = None

    @field_validator("categories")
    @classmethod
    def _known(cls, v):
        if v is not None and any(c not in CATEGORIES for c in v):
            raise ValueError("unknown category")
        return v


class PushTokenIn(BaseModel):
    token: str | None = Field(default=None, max_length=200)


class HideIn(BaseModel):
    reason: Literal["not_interested", "sold"] = "not_interested"


def _err(status: int, code: str, message: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


# ---------------------------------------------------------------- app

def create_app(settings: Settings, api: ApiSettings, *, apple: AppleAppAttest | None = None,
               play: PlayIntegrity | None = None, entitlements_http=None,
               dev_unlock_all: bool = False) -> FastAPI:
    if dev_unlock_all and api.attest_mode != "off":
        raise RuntimeError("DEV_UNLOCK_ALL is only allowed with ATTEST_MODE=off")
    if api.attest_mode == "off":
        log.warning("ATTEST_MODE=off: any client can register. Never run this in production.")
    elif api.attest_mode != "enforce":
        raise RuntimeError("ATTEST_MODE must be 'enforce' or 'off'")
    else:
        if apple is None and api.ios_app_id:
            apple = AppleAppAttest(api.ios_app_id, Path(api.apple_root_ca_path).read_bytes(),
                                   api.ios_attest_env)
        if play is None and api.android_package:
            play = PlayIntegrity(api.android_package, api.play_service_account_json,
                                 api.play_require_licensed)

    app = FastAPI(title="TechFlip API", version="1.0", docs_url=None, redoc_url=None,
                  openapi_url=None)
    if api.cors_origins:  # native apps need none; only a web build would
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=list(api.cors_origins),
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"])
    db_path = settings.db_path
    Store(db_path), Accounts(db_path)  # create schemas once at boot
    windows: dict[str, deque] = defaultdict(deque)

    # ---- per-request resources

    def get_store():
        s = Store(db_path)
        try:
            yield s
        finally:
            s.conn.close()

    def get_accounts():
        a = Accounts(db_path)
        try:
            yield a
        finally:
            a.close()

    def get_ents(accounts: Accounts = Depends(get_accounts)) -> Entitlements:
        return Entitlements(accounts, api.revenuecat_secret_key, api.revenuecat_entitlement,
                            dev_unlock_all=dev_unlock_all, http=entitlements_http)

    def current_user(authorization: str = Header(default=""),
                     accounts: Accounts = Depends(get_accounts)):
        if not authorization.startswith("Bearer "):
            raise _err(401, "unauthenticated")
        try:
            claims = jwt.decode(authorization[7:], api.jwt_secret, algorithms=["HS256"],
                                issuer=ISSUER, options={"require": ["exp", "sub", "iss"]})
        except jwt.ExpiredSignatureError:
            raise _err(401, "token_expired")
        except jwt.InvalidTokenError:
            raise _err(401, "unauthenticated")
        if claims.get("typ") != "access":
            raise _err(401, "unauthenticated")
        user = accounts.user(claims["sub"])
        if user is None or user["status"] != "active" or not accounts.device_exists(claims.get("did", "")):
            raise _err(401, "unauthenticated")
        return user

    def paid_user(user=Depends(current_user), ents: Entitlements = Depends(get_ents)):
        if not ents.is_active(user):
            raise _err(402, "subscription_required", "Abonnement requis")
        return user

    def throttle(user=Depends(paid_user)):
        q = windows[user["id"]]
        now = time.monotonic()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= api.list_calls_per_minute:
            raise _err(429, "rate_limited", "Trop de requêtes, réessaie dans une minute")
        q.append(now)
        return user

    def tokens(accounts: Accounts, user_id: str, device_id: str, family: str | None = None) -> dict:
        now = int(time.time())
        access = jwt.encode({"sub": user_id, "did": device_id, "typ": "access", "iss": ISSUER,
                             "iat": now, "exp": now + api.access_ttl_s}, api.jwt_secret,
                            algorithm="HS256")
        refresh = accounts.issue_refresh(user_id, device_id, api.refresh_ttl_s, family)
        return {"user_id": user_id, "device_id": device_id, "access_token": access,
                "refresh_token": refresh, "expires_in": api.access_ttl_s}

    @app.exception_handler(AttestationError)
    async def _attest_failed(request: Request, exc: AttestationError):
        log.warning("attestation failed: %s", exc)
        return JSONResponse(status_code=401, content={"detail": {
            "code": "attestation_failed", "message": "Appareil ou application non vérifié"}})

    @app.middleware("http")
    async def _no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ---- health

    @app.get("/v1/health")
    def health():
        return {"ok": True}

    # ---- auth

    @app.post("/v1/auth/challenge")
    def challenge(accounts: Accounts = Depends(get_accounts)):
        return {"challenge": accounts.new_challenge(), "expires_in": 300}

    @app.post("/v1/auth/register")
    def register(body: RegisterIn, accounts: Accounts = Depends(get_accounts)):
        if not accounts.consume_challenge(body.challenge):
            raise _err(401, "bad_challenge")
        if api.attest_mode == "off":
            device_id = f"dev:{secrets.token_urlsafe(16)}"
            uid = accounts.create_user(body.platform, device_id)
            return tokens(accounts, uid, device_id)
        if body.platform == "ios":
            if apple is None or not (body.key_id and body.attestation):
                raise _err(400, "attestation_required")
            key = apple.verify_attestation(body.key_id, body.attestation, body.challenge)
            if accounts.device_exists(key.key_id):
                raise _err(409, "device_already_registered")
            uid = accounts.create_user("ios", key.key_id, key.public_key_der, key.receipt)
            return tokens(accounts, uid, key.key_id)
        if body.platform == "android":
            if play is None or not body.integrity_token:
                raise _err(400, "attestation_required")
            play.verify(body.integrity_token, body.challenge)
            device_id = f"android:{secrets.token_urlsafe(16)}"
            uid = accounts.create_user("android", device_id)
            return tokens(accounts, uid, device_id)
        raise _err(400, "attestation_required")

    @app.post("/v1/auth/refresh")
    def refresh(body: RefreshIn, accounts: Accounts = Depends(get_accounts)):
        if not accounts.consume_challenge(body.challenge):
            raise _err(401, "bad_challenge")
        row = accounts.peek_refresh(body.refresh_token)
        if row is None:
            raise _err(401, "session_expired")
        device = accounts.device(row["device_id"])
        user = accounts.user(row["user_id"])
        if device is None or user is None or user["status"] != "active":
            raise _err(401, "session_expired")
        if api.attest_mode == "enforce":
            if device["platform"] == "ios":
                if apple is None or not body.assertion:
                    raise _err(400, "assertion_required")
                counter = apple.verify_assertion(body.assertion, body.challenge,
                                                 device["public_key"], device["counter"])
                accounts.bump_device(device["id"], counter)
            elif device["platform"] == "android":
                if play is None or not body.integrity_token:
                    raise _err(400, "assertion_required")
                play.verify(body.integrity_token, body.challenge)
                accounts.bump_device(device["id"])
            else:
                raise _err(401, "session_expired")
        else:
            accounts.bump_device(device["id"])
        # Consumed only once the device has proven itself. A second use of the
        # same token (a copy) revokes the whole family.
        try:
            row = accounts.use_refresh(body.refresh_token)
        except TokenReuse:
            log.warning("refresh token reuse: session family revoked")
            raise _err(401, "session_revoked")
        if row is None:
            raise _err(401, "session_expired")
        return tokens(accounts, row["user_id"], row["device_id"], row["family"])

    # ---- me

    def me_payload(user, ents: Entitlements) -> dict:
        active = ents.is_active(user)
        return {
            "id": user["id"],
            "prefs": {
                "home_lat": user["home_lat"], "home_lng": user["home_lng"],
                "home_label": user["home_label"], "radius_km": user["radius_km"],
                "include_shipping": bool(user["include_shipping"]),
                "min_profit": user["min_profit"],
                "categories": json.loads(user["categories"] or "[]"),
                "notify": bool(user["notify"]),
            },
            "entitlement": {"active": active, "until": user["entitled_until"] if active else None,
                            "product": user["entitlement_product"] if active else None},
        }

    @app.get("/v1/me")
    def me(user=Depends(current_user), ents: Entitlements = Depends(get_ents)):
        return me_payload(user, ents)

    @app.patch("/v1/me/prefs")
    def update_prefs(body: PrefsIn, user=Depends(current_user),
                     accounts: Accounts = Depends(get_accounts),
                     ents: Entitlements = Depends(get_ents)):
        accounts.update_prefs(user["id"], body.model_dump(exclude_unset=True))
        return me_payload(accounts.user(user["id"]), ents)

    @app.post("/v1/me/push-token")
    def push_token(body: PushTokenIn, user=Depends(current_user),
                   accounts: Accounts = Depends(get_accounts)):
        if body.token is not None and not is_expo_token(body.token):
            raise _err(400, "bad_push_token")
        accounts.set_push_token(user["id"], body.token)
        return {"ok": True}

    @app.post("/v1/me/entitlement/sync")
    def sync_entitlement(user=Depends(current_user), accounts: Accounts = Depends(get_accounts),
                         ents: Entitlements = Depends(get_ents)):
        """Called by the app right after a purchase or restore."""
        ents.refresh(user["id"])
        return me_payload(accounts.user(user["id"]), ents)

    @app.delete("/v1/me")
    def delete_me(user=Depends(current_user), accounts: Accounts = Depends(get_accounts)):
        accounts.delete_user(user["id"])
        return {"ok": True}

    # ---- teaser (signed in, not paid)

    @app.get("/v1/teaser")
    def get_teaser(user=Depends(current_user), store: Store = Depends(get_store)):
        return teaser(store, viewer_for(user, settings), api.deals_max_age_days)

    # ---- deals (paid)

    def need_viewer(user):
        v = viewer_for(user, settings)
        if v is None:
            raise _err(409, "home_required", "Indique ta position dans les réglages")
        return v

    @app.get("/v1/deals")
    def list_deals(sort: str = Query("profit"), category: str | None = Query(None),
                   limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0, le=5000),
                   user=Depends(throttle), store: Store = Depends(get_store),
                   accounts: Accounts = Depends(get_accounts)):
        if sort not in SORTS or (category and category not in CATEGORIES):
            raise _err(400, "bad_query")
        items = deals_for(store, need_viewer(user), api.deals_max_age_days,
                          hidden=accounts.hidden_uids(user["id"]), category=category)
        items = sort_deals(items, sort)
        page = items[offset:offset + limit]
        return {"total": len(items), "items": [card(r, j) for r, j in page],
                "next_offset": offset + limit if offset + limit < len(items) else None}

    @app.get("/v1/deals/map")
    def map_pins(user=Depends(throttle), store: Store = Depends(get_store),
                 accounts: Accounts = Depends(get_accounts)):
        items = deals_for(store, need_viewer(user), api.deals_max_age_days,
                          hidden=accounts.hidden_uids(user["id"]))
        items = [it for it in sort_deals(items, "profit") if it[0]["lat"] is not None][:400]
        return {"items": [dict(pin(r, j), **{"card": card(r, j)}) for r, j in items]}

    @app.get("/v1/deals/{uid:path}")
    def get_deal(uid: str, user=Depends(throttle), store: Store = Depends(get_store),
                 accounts: Accounts = Depends(get_accounts)):
        if accounts.bump_usage(user["id"], "detail") > api.detail_views_per_day:
            log.warning("detail ceiling hit by %s", user["id"])
            raise _err(429, "daily_limit", "Limite quotidienne atteinte")
        row = store.get(uid)
        if row is None or not row["appraisal"]:
            raise _err(404, "not_found")
        j = judge(row, need_viewer(user))
        return detail(store, row, j, uid in accounts.saved_uids(user["id"]))

    @app.get("/v1/saved")
    def saved(user=Depends(throttle), store: Store = Depends(get_store),
              accounts: Accounts = Depends(get_accounts)):
        viewer = need_viewer(user)
        out = []
        for uid in accounts.saved_uids(user["id"]):
            row = store.get(uid)
            if row is None or not row["appraisal"]:
                continue
            c = card(row, judge(row, viewer))
            c["gone"] = row["status"] != "active"
            out.append(c)
        return {"items": out}

    @app.put("/v1/saved/{uid:path}")
    def save(uid: str, user=Depends(paid_user), store: Store = Depends(get_store),
             accounts: Accounts = Depends(get_accounts)):
        if store.get(uid) is None:
            raise _err(404, "not_found")
        accounts.save(user["id"], uid)
        return {"ok": True}

    @app.delete("/v1/saved/{uid:path}")
    def unsave(uid: str, user=Depends(paid_user), accounts: Accounts = Depends(get_accounts)):
        accounts.unsave(user["id"], uid)
        return {"ok": True}

    @app.post("/v1/hidden/{uid:path}")
    def hide(uid: str, body: HideIn, user=Depends(paid_user), store: Store = Depends(get_store),
             accounts: Accounts = Depends(get_accounts)):
        if store.get(uid) is None:
            raise _err(404, "not_found")
        if accounts.hide(user["id"], uid, body.reason) >= 2:
            store.mark_gone(uid)   # two independent "vendu" reports: gone for everyone
        return {"ok": True}

    # ---- RevenueCat webhook

    @app.post("/v1/webhooks/revenuecat")
    def rc_webhook(body: dict = Body(...), authorization: str = Header(default="")):
        if not api.revenuecat_webhook_auth:
            raise _err(503, "webhook_not_configured")
        if not hmac.compare_digest(authorization.encode(), api.revenuecat_webhook_auth.encode()):
            raise _err(401, "unauthenticated")
        accounts = Accounts(db_path)
        try:
            ents = Entitlements(accounts, api.revenuecat_secret_key, api.revenuecat_entitlement,
                                http=entitlements_http)
            touched = ents.handle_webhook(body)
        finally:
            accounts.close()
        return {"ok": True, "synced": len(touched)}

    app.state.started_at = datetime.now(timezone.utc).isoformat()
    return app
