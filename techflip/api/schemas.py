"""Request bodies. Validation lives here, so routes only deal with valid input."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .deals import CATEGORIES


class RegisterIn(BaseModel):
    platform: Literal["ios", "android", "dev"]
    challenge: str = Field(max_length=200)
    key_id: str | None = Field(default=None, max_length=200)             # iOS
    attestation: str | None = Field(default=None, max_length=20000)      # iOS
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
    notify_mode: Literal["instant", "daily"] | None = None

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


class FeedbackIn(BaseModel):
    """Is our estimate right? And, once they resold it, for how much."""
    verdict: Literal["low", "fair", "high"] | None = None
    resale_price: float | None = Field(default=None, gt=0, le=20000)
