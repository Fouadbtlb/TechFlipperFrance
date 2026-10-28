"""Configuration.

Two layers:
- .env                 -> secrets & runtime knobs (tokens, thresholds, API keys)
- config/searches.yaml -> the searches to monitor (paste Leboncoin URLs)

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
    poll_seconds_min: int = 90
    poll_seconds_max: int = 240
    night_pause: bool = True
    impersonate: str = "safari_ios"
    ai_url: str = "http://localhost:11434/v1"
    ai_model: str = "qwen2.5vl:7b"
    # qwen2.5vl:7b ships a 4096-token context; one full-res photo plus the prompt
    # already fills most of it, so keep this at 1 unless the model has more ctx.
    ai_max_images: int = 1
    # pricing
    pricebook_path: str = "config/pricebook.yaml"
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
    searches: tuple[SearchConfig, ...] = field(default_factory=tuple)


def _f(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v else default


def load_settings(searches_file: str | Path = "config/searches.yaml") -> Settings:
    searches: list[SearchConfig] = []
    path = Path(searches_file)
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        default_exclude = tuple(raw.get("default_exclude", []))
        env_cap = os.environ.get("MAX_PRICE")
        price_cap = float(env_cap) if env_cap else None
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
        poll_seconds_min=int(os.environ.get("POLL_SECONDS_MIN", 90)),
        poll_seconds_max=int(os.environ.get("POLL_SECONDS_MAX", 240)),
        night_pause=os.environ.get("NIGHT_PAUSE", "1") != "0",
        impersonate=os.environ.get("LBC_IMPERSONATE", "safari_ios"),
        ai_url=os.environ.get("AI_URL", "http://localhost:11434/v1"),
        ai_model=os.environ.get("AI_MODEL", "qwen2.5vl:7b"),
        ai_max_images=int(os.environ.get("AI_MAX_IMAGES", 1)),
        pricebook_path=os.environ.get("PRICEBOOK", "config/pricebook.yaml"),
        min_comparables=int(os.environ.get("MIN_COMPARABLES", 5)),
        window_days=int(os.environ.get("WINDOW_DAYS", 90)),
        realization_factor=_f("REALIZATION_FACTOR", 0.85),
        max_eval_price=_f("MAX_EVAL_PRICE", 1500),
        home=(_f("HOME_LAT", 50.6292), _f("HOME_LNG", 3.0573)),
        home_label=os.environ.get("HOME_LABEL", "Lille"),
        easy_km=_f("EASY_KM", 60),
        medium_km=_f("MEDIUM_KM", 150),
        cost_per_km=_f("COST_PER_KM", 0.25),
        easy_bar=_f("EASY_BAR", 30),
        medium_bar=_f("MEDIUM_BAR", 80),
        hard_bar=_f("HARD_BAR", 120),
        min_conf_medium=_f("MIN_CONF_MEDIUM", 0.4),
        min_conf_hard=_f("MIN_CONF_HARD", 0.6),
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
        access_ttl_s=int(os.environ.get("ACCESS_TTL_S", 900)),
        refresh_ttl_s=int(os.environ.get("REFRESH_TTL_S", 60 * 86400)),
        attest_mode=os.environ.get("ATTEST_MODE", "enforce"),
        ios_app_id=os.environ.get("IOS_APP_ID", ""),
        ios_attest_env=os.environ.get("IOS_ATTEST_ENV", "production"),
        apple_root_ca_path=os.environ.get(
            "APPLE_ROOT_CA", "config/Apple_App_Attestation_Root_CA.pem"),
        android_package=os.environ.get("ANDROID_PACKAGE", ""),
        play_service_account_json=os.environ.get("PLAY_SERVICE_ACCOUNT_JSON", ""),
        play_require_licensed=os.environ.get("PLAY_REQUIRE_LICENSED", "1") != "0",
        revenuecat_secret_key=os.environ.get("REVENUECAT_SECRET_KEY", ""),
        revenuecat_entitlement=os.environ.get("REVENUECAT_ENTITLEMENT", "pro"),
        revenuecat_webhook_auth=os.environ.get("REVENUECAT_WEBHOOK_AUTH", ""),
        expo_access_token=os.environ.get("EXPO_ACCESS_TOKEN", ""),
        deals_max_age_days=int(os.environ.get("DEALS_MAX_AGE_DAYS", 7)),
        detail_views_per_day=int(os.environ.get("DETAIL_VIEWS_PER_DAY", 400)),
        list_calls_per_minute=int(os.environ.get("LIST_CALLS_PER_MINUTE", 60)),
        cors_origins=tuple(o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o),
    )
