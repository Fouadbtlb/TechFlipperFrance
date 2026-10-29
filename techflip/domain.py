"""Canonical domain model, source-agnostic.

Every source (Leboncoin, 2ememain) is normalized into `Listing`. Valuation,
storage, the API and alerts only ever see this model, so adding a source never
touches the rest of the pipeline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class Listing:
    # Identity
    source: str                 # "leboncoin", "2ememain", "cashconverters", "cashexpress"
    source_id: str              # id on the source site
    url: str

    # Core facts
    title: str
    price: float | None
    published_at: str | None    # ISO string from the source

    # Product attributes
    brand: str | None = None
    model: str | None = None
    condition: str | None = None

    # Context
    description: str = ""
    city: str | None = None
    zipcode: str | None = None
    department: str | None = None
    lat: float | None = None
    lng: float | None = None
    country: str = "FR"             # "FR" / "BE"
    owner_type: str | None = None   # "private" / "pro" (unknown at search time on LBC)
    has_phone: bool = False
    seller_id: str | None = None    # source-side user id, for lazy profile enrichment
    image_urls: tuple[str, ...] = field(default_factory=tuple)
    # The aisle the source filed it under, when it states one: a listing under
    # /jeux-playstation/ is a game, whatever console its title names.
    source_category: str | None = None

    # Bookkeeping
    search_name: str = ""       # which configured search found it
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def uid(self) -> str:
        """Globally unique id across sources."""
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["image_urls"] = list(self.image_urls)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Listing:
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        clean["image_urls"] = tuple(clean.get("image_urls") or ())
        return cls(**clean)


@dataclass(frozen=True)
class SellerInfo:
    """Seller profile, fetched lazily (one extra request) for deals only.

    This is the trust layer: a week-old account selling 30% under market
    is a scam, not a deal.
    """
    seller_id: str
    name: str | None = None
    account_type: str | None = None   # "private" / "pro"
    registered_at: str | None = None  # ISO-ish date string from the source
    total_ads: int | None = None
    feedback_score: float | None = None   # 0-5
    feedback_count: int | None = None


@dataclass(frozen=True)
class ScoreResult:
    """Output of a scorer for one tech listing."""
    listing_uid: str
    true_value: float | None        # estimated fair price of the entire bundle
    net_profit: float | None        # total value - (price + logistics)
    bundle_details: dict | None     # raw JSON from LLM
    reasons: tuple[str, ...] = ()   # human-readable explanation
