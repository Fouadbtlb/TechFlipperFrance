"""Source interface: implement this to plug in a new site.

Contract:
- `name`: short source id, stored on every Listing (`Listing.source`).
- `fetch(search, page=1)`: return the listings for one configured search,
  newest first. Page 1 must be enough for live polling; higher pages are only
  used by the one-shot `bootstrap` warm-up.
- OPTIONAL `fetch_seller(seller_id) -> SellerInfo | None`: lazy seller-profile
  enrichment (Leboncoin needs a 2nd request; AutoScout ships it in the listing).
  Sources without it are detected via `getattr(source, "fetch_seller", None)`.

Everything downstream sees only the canonical `Listing`, so a new source never
touches scoring, filters, storage or alerts.
"""
from __future__ import annotations

from typing import Protocol

from ..config import SearchConfig
from ..domain import Listing


class Source(Protocol):
    name: str

    def fetch(self, search: SearchConfig, page: int = 1) -> list[Listing]:
        ...
