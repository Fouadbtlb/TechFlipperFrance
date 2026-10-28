"""FastAPI dependencies: who is calling, may they, and the per-request
resources they get. A route declares what it needs in its signature:

    def list_deals(user: ThrottledUser, store: StoreDep, viewer: ViewerDep): ...

and the chain below does the rest (authentication -> subscription -> rate
limit -> home location), each step failing with a clear JSON error.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request

from ..storage import Store
from ..viewer import Viewer
from .accounts import Accounts
from .deals import viewer_for
from .entitlements import Entitlements
from .services import Services

NOT_FOUND = "Cette annonce a été retirée ou n’existe plus."


def api_error(status: int, code: str, message: str = "") -> HTTPException:
    """All API errors share one shape: {"detail": {"code", "message"}}.
    `code` is for the app's logic, `message` (French) for people."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_store(svc: ServicesDep) -> Iterator[Store]:
    store = Store(svc.settings.db_path)
    try:
        yield store
    finally:
        store.close()


def get_accounts(svc: ServicesDep) -> Iterator[Accounts]:
    accounts = Accounts(svc.settings.db_path)
    try:
        yield accounts
    finally:
        accounts.close()


StoreDep = Annotated[Store, Depends(get_store)]
AccountsDep = Annotated[Accounts, Depends(get_accounts)]


def get_entitlements(svc: ServicesDep, accounts: AccountsDep) -> Entitlements:
    return Entitlements(accounts, svc.api.revenuecat_secret_key, svc.api.revenuecat_entitlement,
                        dev_unlock_all=svc.dev_unlock_all, http=svc.http)


EntitlementsDep = Annotated[Entitlements, Depends(get_entitlements)]


def current_user(svc: ServicesDep, accounts: AccountsDep,
                 authorization: Annotated[str, Header()] = "") -> sqlite3.Row:
    if not authorization.startswith("Bearer "):
        raise api_error(401, "unauthenticated")
    try:
        claims = svc.tokens.decode(authorization[7:])
    except jwt.ExpiredSignatureError:
        raise api_error(401, "token_expired") from None
    except jwt.InvalidTokenError:
        raise api_error(401, "unauthenticated") from None
    user = accounts.user(claims["sub"])
    if user is None or user["status"] != "active" or not accounts.device_exists(claims.get("did", "")):
        raise api_error(401, "unauthenticated")
    return user


CurrentUser = Annotated[sqlite3.Row, Depends(current_user)]


def paid_user(user: CurrentUser, ents: EntitlementsDep) -> sqlite3.Row:
    if not ents.is_active(user):
        raise api_error(402, "subscription_required", "Abonnement requis")
    return user


PaidUser = Annotated[sqlite3.Row, Depends(paid_user)]


def throttled_user(user: PaidUser, svc: ServicesDep) -> sqlite3.Row:
    if not svc.limiter.allow(user["id"]):
        raise api_error(429, "rate_limited", "Trop de demandes d’un coup, réessaie dans une minute")
    return user


ThrottledUser = Annotated[sqlite3.Row, Depends(throttled_user)]


def viewer(user: ThrottledUser, svc: ServicesDep) -> Viewer:
    """The paying user's point of view (home, bar, radius). Chained after the
    paywall and the rate limit, so those errors always come first."""
    v = viewer_for(user, svc.settings)
    if v is None:
        raise api_error(409, "home_required", "Indique ta position dans les réglages")
    return v


ViewerDep = Annotated[Viewer, Depends(viewer)]
