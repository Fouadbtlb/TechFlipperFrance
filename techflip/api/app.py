"""TechFlip app backend: assembly only.

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

Where things live: services.py (long-lived objects), deps.py (who is calling
and what they may do), schemas.py (request bodies), routes/ (one module per
domain). See docs/ARCHITECTURE.md.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from ..config import ApiSettings, Settings
from ..storage import Store
from .accounts import Accounts
from .attest import AppleAppAttest, AttestationError, PlayIntegrity
from .routes import auth, feed, me, system
from .services import build_services

log = logging.getLogger(__name__)


def create_app(settings: Settings, api: ApiSettings, *, apple: AppleAppAttest | None = None,
               play: PlayIntegrity | None = None, entitlements_http=None,
               dev_unlock_all: bool = False) -> FastAPI:
    services = build_services(settings, api, apple=apple, play=play, http=entitlements_http,
                              dev_unlock_all=dev_unlock_all)
    # Create or upgrade both schemas once, at boot, not on the first request.
    Store(settings.db_path).close()
    Accounts(settings.db_path).close()

    app = FastAPI(title="TechFlip API", version="1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services

    # JSON lists compress very well: much less mobile data for the feed and map.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if api.cors_origins:  # native apps need none; only a web build would
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=list(api.cors_origins),
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def _no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"   # paid data: never cached by a proxy
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AttestationError)
    async def _attestation_failed(request: Request, exc: AttestationError):
        log.warning("attestation failed: %s", exc)
        return JSONResponse(status_code=401, content={"detail": {
            "code": "attestation_failed", "message": "Impossible de vérifier ton appareil ou l’application"}})

    for module in (system, auth, me, feed):
        app.include_router(module.router)
    return app
