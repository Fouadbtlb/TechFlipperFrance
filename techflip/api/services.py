"""Long-lived objects the API needs, built once at startup.

Routes never construct these themselves: they receive them through the
dependencies in deps.py, which makes every endpoint easy to read and to test
(pass fakes to create_app, the routes do not change).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import jwt

from ..config import ApiSettings, Settings
from .accounts import Accounts
from .attest import AppleAppAttest, PlayIntegrity

log = logging.getLogger(__name__)

ISSUER = "techflip"


class RateLimiter:
    """Sliding one-minute window per key, in memory (one API process).
    Idle keys are dropped so the table cannot grow without bound."""

    def __init__(self, per_minute: int, window_s: float = 60.0):
        self.per_minute = per_minute
        self.window_s = window_s
        self._hits: dict[str, deque] = {}
        self._last_sweep = time.monotonic()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        if now - self._last_sweep > 10 * self.window_s:
            self._sweep(now)
        return True

    def _sweep(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window_s]:
            del self._hits[k]
        self._last_sweep = now


@dataclass
class TokenIssuer:
    """Short-lived access JWTs + rotating refresh tokens (stored hashed)."""
    secret: str
    access_ttl_s: int
    refresh_ttl_s: int

    def issue(self, accounts: Accounts, user_id: str, device_id: str, family: str | None = None) -> dict:
        now = int(time.time())
        access = jwt.encode({"sub": user_id, "did": device_id, "typ": "access", "iss": ISSUER,
                             "iat": now, "exp": now + self.access_ttl_s}, self.secret, algorithm="HS256")
        refresh = accounts.issue_refresh(user_id, device_id, self.refresh_ttl_s, family)
        return {"user_id": user_id, "device_id": device_id, "access_token": access,
                "refresh_token": refresh, "expires_in": self.access_ttl_s}

    def decode(self, token: str) -> dict:
        """Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError."""
        claims = jwt.decode(token, self.secret, algorithms=["HS256"], issuer=ISSUER,
                            options={"require": ["exp", "sub", "iss"]})
        if claims.get("typ") != "access":
            raise jwt.InvalidTokenError("not an access token")
        return claims


@dataclass
class Services:
    settings: Settings
    api: ApiSettings
    tokens: TokenIssuer
    limiter: RateLimiter
    http: httpx.Client                 # shared connection pool (RevenueCat)
    apple: AppleAppAttest | None = None
    play: PlayIntegrity | None = None
    dev_unlock_all: bool = False
    extras: dict = field(default_factory=dict)

    @property
    def enforce_attestation(self) -> bool:
        return self.api.attest_mode == "enforce"


def build_services(settings: Settings, api: ApiSettings, *, apple: AppleAppAttest | None = None,
                   play: PlayIntegrity | None = None, http: httpx.Client | None = None,
                   dev_unlock_all: bool = False) -> Services:
    """Validate the security configuration and assemble the services. Refuses
    combinations that would be unsafe in production."""
    if api.attest_mode not in ("enforce", "off"):
        raise RuntimeError("ATTEST_MODE must be 'enforce' or 'off'")
    if dev_unlock_all and api.attest_mode != "off":
        raise RuntimeError("DEV_UNLOCK_ALL is only allowed with ATTEST_MODE=off")
    if api.attest_mode == "off":
        log.warning("ATTEST_MODE=off: any client can register. Never run this in production.")
    else:
        if apple is None and api.ios_app_id:
            apple = AppleAppAttest(api.ios_app_id, Path(api.apple_root_ca_path).read_bytes(), api.ios_attest_env)
        if play is None and api.android_package:
            play = PlayIntegrity(api.android_package, api.play_service_account_json, api.play_require_licensed)
    return Services(
        settings=settings,
        api=api,
        tokens=TokenIssuer(api.jwt_secret, api.access_ttl_s, api.refresh_ttl_s),
        limiter=RateLimiter(api.list_calls_per_minute),
        http=http or httpx.Client(timeout=10),
        apple=apple,
        play=play,
        dev_unlock_all=dev_unlock_all,
    )
