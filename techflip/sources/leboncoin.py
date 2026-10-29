"""Leboncoin source, backed by the unofficial `lbc` client (curl-cffi).

Anti-detection posture:
- The lbc client sends a Leboncoin MOBILE APP user-agent, so the TLS
  fingerprint must match a mobile stack. Which one passes is not stable:
  "safari_ios" on 2026-07-20, only "chrome_android" on 2026-08-12. Re-test
  (LBC_IMPERSONATE) rather than trust the default.
- ONE consistent fingerprint per process (rotating looks robotic).
- max_retries=1: retry storms make DataDome flag the IP harder; real backoff
  lives in the pipeline.
- The proxy goes to the lbc constructor. lbc's first request (cookies) is
  made while it is being built, and it rebuilds its session after a DataDome
  block from the proxy it was given: a proxy set afterwards would let both go
  out from the real IP.
- Newest first, written into the URL: lbc ignores its `sort` argument when a
  URL is given.
- The client is built on first use: lbc requests the site while it is being
  built, and an unreachable Leboncoin must cost one failed search, not stop
  the scanner from starting.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

import lbc

from .. import tuning
from ..config import SearchConfig
from ..domain import Listing, SellerInfo
from ..liveness import query_for

log = logging.getLogger(__name__)

_SOLD_WORDS = ("vendu", "réservé", "reserve", "achat en cours")


class LeboncoinSource:
    name = "leboncoin"

    def __init__(self, proxy: str | None = None, impersonate: str = "chrome_android"):
        self._proxy = _lbc_proxy(proxy)
        self._impersonate = impersonate
        self._client = None

    @property
    def client(self) -> lbc.Client:
        if self._client is None:
            self._client = lbc.Client(proxy=self._proxy, impersonate=self._impersonate, max_retries=1)
        return self._client

    def fetch(self, search: SearchConfig, page: int = 1) -> list[Listing]:
        result = self.client.search(url=_newest_first(search.url), limit=35, page=page)
        listings = []
        for ad in result.ads:
            if getattr(ad, "status", "active") != "active":
                continue
            if any(k in (ad.subject or "").lower() for k in _SOLD_WORDS):
                continue
            try:
                listings.append(self._normalize(ad, search.name))
            except Exception:
                log.exception("Failed to normalize ad %s", getattr(ad, "id", "?"))
        return listings

    def is_online(self, row) -> bool | None:
        """Still for sale? The ad page cannot say: Leboncoin answers HTTP 410
        with the same body for live and expired ads (measured 2026-08-18). So
        re-run a search narrow enough that a live ad must come back: its title
        words, a price band around its price (sellers cut), 10 km around it.
        None when the listing lacks what that search needs. DataDome errors
        propagate so the caller can back off."""
        query = query_for(row["title"])
        if not query or not row["price"] or row["lat"] is None or row["lng"] is None:
            return None
        price, (low, high), radius = int(row["price"]), tuning.RECHECK_PRICE_BAND, tuning.RECHECK_RADIUS_M
        url = (f"https://www.leboncoin.fr/recherche?text={query}"
               f"&price={int(price * low)}-{int(price * high) + 1}"
               f"&locations=zone__{row['lat']}_{row['lng']}_{radius}_{radius}")
        return row["source_id"] in {str(ad.id) for ad in self.client.search(url=url, limit=35).ads}

    def fetch_seller(self, seller_id: str) -> SellerInfo | None:
        """One extra request. Call only for listings that scored as deals."""
        try:
            u = self.client.get_user(user_id=seller_id)
        except Exception:
            log.warning("Seller fetch failed for %s", seller_id, exc_info=True)
            return None
        fb = u.feedback
        return SellerInfo(
            seller_id=seller_id,
            name=u.name,
            account_type=u.account_type,
            registered_at=u.registered_at,
            total_ads=u.total_ads,
            feedback_score=fb.score if fb else None,
            feedback_count=int(fb.received_count) if fb and fb.received_count else None,
        )

    # ---------- normalization ----------

    def _normalize(self, ad, search_name: str) -> Listing:
        attrs = ad.attributes or {}

        def attr_label(key: str) -> str | None:
            a = attrs.get(key)
            return (a.value_label or a.value) if a else None

        loc = ad.location
        return Listing(
            source=self.name,
            source_id=str(ad.id),
            url=ad.url,
            title=ad.subject or "",
            price=ad.price,
            published_at=ad.first_publication_date,
            brand=attr_label("brand"),
            model=attr_label("model"),
            condition=attr_label("etat") or attr_label("condition") or None,
            description=ad.body or "",
            city=loc.city if loc else None,
            zipcode=loc.zipcode if loc else None,
            department=loc.department_name if loc else None,
            lat=loc.lat if loc else None,
            lng=loc.lng if loc else None,
            country="FR",
            owner_type=None,
            has_phone=bool(ad.has_phone),
            seller_id=str(getattr(ad, "_user_id", "") or "") or None,
            image_urls=tuple(ad.images or []),
            search_name=search_name,
        )


def _newest_first(url: str) -> str:
    if re.search(r"[?&]sort=", url):
        return url
    return f"{url}{'&' if '?' in url else '?'}sort=time&order=desc"


def _lbc_proxy(url: str | None) -> lbc.Proxy | None:
    """"http://user:pass@host:port" -> lbc.Proxy."""
    if not url:
        return None
    u = urllib.parse.urlsplit(url)
    if not u.hostname or not u.port:
        raise ValueError(f"proxy invalide (attendu http://hote:port): {url!r}")
    # Credentials stay percent-encoded: lbc pastes them back into a URL.
    return lbc.Proxy(host=u.hostname, port=u.port, scheme=u.scheme or "http",
                     username=u.username, password=u.password)
