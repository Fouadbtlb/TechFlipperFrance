"""Configuration.

Two layers:
- .env                 -> secrets & runtime knobs (tokens, thresholds, API keys)
- config/searches.yaml -> the searches to monitor (paste Leboncoin URLs), and
                          optionally a `proxy:` for the scrapers
- config/sold.yaml     -> what you actually sold things for

The API's settings live in their own dataclass (ApiSettings) so the scanner can
run on a box that has none of the app secrets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class SearchConfig:
    name: str
    url: str
    source: str = "leboncoin"
    kind: str = "hunt"              # "hunt" = appraise & alert · "feeder" = learn prices only
    min_price: float = 20
    max_price: float | None = None
    require: tuple[str, ...] = ()   # regexes; ALL must match title+description
    exclude: tuple[str, ...] = ()   # regexes; NONE may match


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_chat_id: str
    db_path: Path
    # Proxy for every scraper ("http://user:pass@host:port"), None = direct.
    proxy: str | None = None
    poll_seconds_min: int = 90
    poll_seconds_max: int = 240
    night_pause: bool = True
    # Leboncoin TLS fingerprint. Which mobile stack DataDome lets through
    # changes over time (safari_ios in July 2026, chrome_android in August):
    # re-test rather than trust this default.
    impersonate: str = "chrome_android"
    ai_url: str = "http://localhost:11434/v1"
    ai_model: str = "qwen2.5vl:7b"
    # qwen2.5vl:7b ships a 4096-token context; one full-res photo plus the prompt
    # already fills most of it, so keep this at 1 unless the model has more ctx.
    ai_max_images: int = 1
    # The vision model only runs on candidates worth at least this much (EUR):
    # CPU inference on photos is slow and heats the machine.
    ai_min_margin: float = 70
    # pricing
    pricebook_path: str = "config/pricebook.yaml"
    sold_path: str = "config/sold.yaml"
    min_comparables: int = 5
    window_days: int = 90
    realization_factor: float = 0.85
    max_eval_price: float = 1500
    # owner's home: origin for Telegram alerts and the default app origin
    home: tuple[float, float] = (50.6292, 3.0573)
    home_label: str = "Lille"
    # geo (km) + logistics
    easy_km: float = 60
    medium_km: float = 150
    cost_per_km: float = 0.25
    # decision bars (EUR) + confidence floors
    easy_bar: float = 30
    medium_bar: float = 80
    hard_bar: float = 120
    min_conf_medium: float = 0.4
    min_conf_hard: float = 0.6
    # listings re-checked per cycle to learn what left the site (sold or withdrawn)
    departure_checks: int = 12
    # shopping board: asking prices of ads still online after this many days
    # are left out of its medians (they did not sell at that price)
    stale_days: float = 10
    searches: tuple[SearchConfig, ...] = field(default_factory=tuple)


def _float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v else default


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if not v else v not in ("0", "false", "no")


def load_settings(searches_file: str | Path | None = None) -> Settings:
    """`searches_file` defaults to $SEARCHES_FILE, then config/searches.yaml."""
    path = Path(searches_file or os.environ.get("SEARCHES_FILE") or "config/searches.yaml")
    searches: list[SearchConfig] = []
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        default_exclude = tuple(raw.get("default_exclude", []))
        price_cap = _float("MAX_PRICE", 0) or None
        for item in raw.get("searches", []):
            mp = item.get("max_price")
            if price_cap is not None:
                mp = price_cap if mp is None else min(mp, price_cap)
            searches.append(
                SearchConfig(
                    name=item["name"],
                    url=item["url"],
                    source=item.get("source", "leboncoin"),
                    kind=item.get("kind", "hunt"),
                    min_price=float(item.get("min_price", 20)),
                    max_price=mp,
                    require=tuple(item.get("require", [])),
                    exclude=default_exclude + tuple(item.get("exclude", [])),
                )
            )

    return Settings(
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        db_path=Path(os.environ.get("TECHFLIP_DB", "techflip.db")),
        proxy=os.environ.get("PROXY_URL") or raw.get("proxy") or None,
        poll_seconds_min=_int("POLL_SECONDS_MIN", 90),
        poll_seconds_max=_int("POLL_SECONDS_MAX", 240),
        night_pause=_bool("NIGHT_PAUSE", True),
        impersonate=os.environ.get("LBC_IMPERSONATE", "chrome_android"),
        ai_url=os.environ.get("AI_URL", "http://localhost:11434/v1"),
        ai_model=os.environ.get("AI_MODEL", "qwen2.5vl:7b"),
        ai_max_images=_int("AI_MAX_IMAGES", 1),
        ai_min_margin=_float("AI_MIN_MARGIN", 70),
        pricebook_path=os.environ.get("PRICEBOOK", "config/pricebook.yaml"),
        sold_path=os.environ.get("SOLD_PRICES", "config/sold.yaml"),
        min_comparables=_int("MIN_COMPARABLES", 5),
        window_days=_int("WINDOW_DAYS", 90),
        realization_factor=_float("REALIZATION_FACTOR", 0.85),
        max_eval_price=_float("MAX_EVAL_PRICE", 1500),
        home=(_float("HOME_LAT", 50.6292), _float("HOME_LNG", 3.0573)),
        home_label=os.environ.get("HOME_LABEL", "Lille"),
        easy_km=_float("EASY_KM", 60),
        medium_km=_float("MEDIUM_KM", 150),
        cost_per_km=_float("COST_PER_KM", 0.25),
        easy_bar=_float("EASY_BAR", 30),
        medium_bar=_float("MEDIUM_BAR", 80),
        hard_bar=_float("HARD_BAR", 120),
        min_conf_medium=_float("MIN_CONF_MEDIUM", 0.4),
        min_conf_hard=_float("MIN_CONF_HARD", 0.6),
        departure_checks=_int("DEPARTURE_CHECKS", 12),
        stale_days=_float("STALE_DAYS", 10),
        searches=tuple(searches),
    )


@dataclass(frozen=True)
class ApiSettings:
    """Everything the paid-app backend needs. See docs/SECURITY.md."""
    jwt_secret: str
    access_ttl_s: int = 900                 # 15 min: a stolen token dies fast
    refresh_ttl_s: int = 60 * 86400
    # "enforce" in production. "off" only for local dev / simulators, where
    # neither App Attest nor Play Integrity exist.
    attest_mode: str = "enforce"
    ios_app_id: str = ""                    # TEAMID.bundle.id
    ios_attest_env: str = "production"      # or "development"
    apple_root_ca_path: str = "config/Apple_App_Attestation_Root_CA.pem"
    android_package: str = ""
    play_service_account_json: str = ""     # path to a GCP service-account key
    play_require_licensed: bool = True
    revenuecat_secret_key: str = ""         # sk_... (server-only, never in the app)
    revenuecat_entitlement: str = "pro"
    revenuecat_webhook_auth: str = ""       # value RevenueCat sends in Authorization
    expo_access_token: str = ""             # optional, enables Expo push security
    deals_max_age_days: int = 7
    detail_views_per_day: int = 400         # abuse ceiling, far above human use
    list_calls_per_minute: int = 60
    cors_origins: tuple[str, ...] = ()


def load_api_settings() -> ApiSettings:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to a random string of 32+ chars "
                           "(python -c 'import secrets;print(secrets.token_urlsafe(48))')")
    return ApiSettings(
        jwt_secret=secret,
        access_ttl_s=_int("ACCESS_TTL_S", 900),
        refresh_ttl_s=_int("REFRESH_TTL_S", 60 * 86400),
        attest_mode=os.environ.get("ATTEST_MODE", "enforce"),
        ios_app_id=os.environ.get("IOS_APP_ID", ""),
        ios_attest_env=os.environ.get("IOS_ATTEST_ENV", "production"),
        apple_root_ca_path=os.environ.get(
            "APPLE_ROOT_CA", "config/Apple_App_Attestation_Root_CA.pem"),
        android_package=os.environ.get("ANDROID_PACKAGE", ""),
        play_service_account_json=os.environ.get("PLAY_SERVICE_ACCOUNT_JSON", ""),
        play_require_licensed=_bool("PLAY_REQUIRE_LICENSED", True),
        revenuecat_secret_key=os.environ.get("REVENUECAT_SECRET_KEY", ""),
        revenuecat_entitlement=os.environ.get("REVENUECAT_ENTITLEMENT", "pro"),
        revenuecat_webhook_auth=os.environ.get("REVENUECAT_WEBHOOK_AUTH", ""),
        expo_access_token=os.environ.get("EXPO_ACCESS_TOKEN", ""),
        deals_max_age_days=_int("DEALS_MAX_AGE_DAYS", 7),
        detail_views_per_day=_int("DETAIL_VIEWS_PER_DAY", 400),
        list_calls_per_minute=_int("LIST_CALLS_PER_MINUTE", 60),
        cors_origins=tuple(o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o),
    )
