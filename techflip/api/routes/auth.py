"""Device-bound anonymous accounts: challenge -> register -> refresh.

Every registration and every refresh carries a device proof (App Attest on
iOS, Play Integrity on Android) bound to a single-use server challenge.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter

from ..accounts import Accounts, TokenReuse
from ..deps import AccountsDep, ServicesDep, api_error
from ..schemas import RefreshIn, RegisterIn
from ..services import Services

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/challenge")
def challenge(accounts: AccountsDep):
    return {"challenge": accounts.new_challenge(), "expires_in": 300}


@router.post("/register")
def register(body: RegisterIn, accounts: AccountsDep, svc: ServicesDep):
    if not accounts.consume_challenge(body.challenge):
        raise api_error(401, "bad_challenge")
    platform, device_id, public_key, receipt = _verify_new_device(svc, accounts, body)
    user_id = accounts.create_user(platform, device_id, public_key, receipt)
    return svc.tokens.issue(accounts, user_id, device_id)


@router.post("/refresh")
def refresh(body: RefreshIn, accounts: AccountsDep, svc: ServicesDep):
    if not accounts.consume_challenge(body.challenge):
        raise api_error(401, "bad_challenge")
    row = accounts.peek_refresh(body.refresh_token)
    device = accounts.device(row["device_id"]) if row else None
    user = accounts.user(row["user_id"]) if row else None
    if device is None or user is None or user["status"] != "active":
        raise api_error(401, "session_expired")
    _verify_known_device(svc, accounts, device, body)
    # Consumed only once the device has proven itself; a second use of the same
    # token (a copy) revokes the whole session family.
    try:
        row = accounts.use_refresh(body.refresh_token)
    except TokenReuse:
        log.warning("refresh token reuse: session family revoked")
        raise api_error(401, "session_revoked") from None
    if row is None:
        raise api_error(401, "session_expired")
    return svc.tokens.issue(accounts, row["user_id"], row["device_id"], row["family"])


# ---------------------------------------------------------------- device proofs

def _verify_new_device(svc: Services, accounts: Accounts, body: RegisterIn):
    """Returns (platform, device_id, public_key, receipt) for a proven device."""
    if not svc.enforce_attestation:
        return body.platform, f"dev:{secrets.token_urlsafe(16)}", None, None
    if body.platform == "ios" and svc.apple and body.key_id and body.attestation:
        key = svc.apple.verify_attestation(body.key_id, body.attestation, body.challenge)
        if accounts.device_exists(key.key_id):
            raise api_error(409, "device_already_registered")
        return "ios", key.key_id, key.public_key_der, key.receipt
    if body.platform == "android" and svc.play and body.integrity_token:
        svc.play.verify(body.integrity_token, body.challenge)
        return "android", f"android:{secrets.token_urlsafe(16)}", None, None
    raise api_error(400, "attestation_required")


def _verify_known_device(svc: Services, accounts: Accounts, device, body: RefreshIn) -> None:
    if not svc.enforce_attestation:
        accounts.bump_device(device["id"])
        return
    if device["platform"] == "ios":
        if not (svc.apple and body.assertion):
            raise api_error(400, "assertion_required")
        counter = svc.apple.verify_assertion(body.assertion, body.challenge, device["public_key"], device["counter"])
        accounts.bump_device(device["id"], counter)
    elif device["platform"] == "android":
        if not (svc.play and body.integrity_token):
            raise api_error(400, "assertion_required")
        svc.play.verify(body.integrity_token, body.challenge)
        accounts.bump_device(device["id"])
    else:  # a dev device cannot refresh once attestation is enforced
        raise api_error(401, "session_expired")
