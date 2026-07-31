"""2ememain.be source - Belgian marketplace (Adevinta), right next to Lille.

Clean JSON API (/lrp/api/search). Belgian listings carry real lat/lng, so the
Lille-distance zoning is exact with no postal database. Same canonical Listing
as every source; paste a 2ememain search-API URL per search in searches.yaml.
"""
from __future__ import annotations

import logging
import re

from curl_cffi import requests

from ..config import SearchConfig
from ..domain import Listing

log = logging.getLogger(__name__)

_BASE = "https://www.2ememain.be"
_LIMIT = 30


class DeuxiemeMainSource:
    name = "2ememain"

    def __init__(self, impersonate: str = "chrome131", timeout: float = 25.0):
        self.session = requests.Session(impersonate=impersonate)
        self.timeout = timeout
        self._warm = False

    def fetch(self, search: SearchConfig, page: int = 1) -> list[Listing]:
        if not self._warm:
            try:
                self.session.get(f"{_BASE}/", timeout=self.timeout)
                self._warm = True
            except Exception:
                log.warning("2ememain: cookie warm-up failed")
        url = _with_offset(search.url, (page - 1) * _LIMIT)
        r = self.session.get(url, timeout=self.timeout, headers={"Accept": "application/json"})
        if "json" not in r.headers.get("content-type", ""):
            log.warning("2ememain: non-JSON (HTTP %s) - blocked?", r.status_code)
            return []
        raw = (r.json() or {}).get("listings") or []
        out = []
        for it in raw:
            try:
                out.append(self._normalize(it, search.name))
            except Exception:
                log.exception("2ememain: normalization failed")
        return out

    def _normalize(self, it: dict, search_name: str) -> Listing:
        loc = it.get("location") or {}
        seller = it.get("sellerInformation") or {}
        cents = (it.get("priceInfo") or {}).get("priceCents")
        price = cents / 100 if cents else None
        vip = it.get("vipUrl") or ""
        url = _BASE + vip if vip.startswith("/") else vip
        return Listing(
            source=self.name,
            source_id=str(it.get("itemId") or url),
            url=url,
            title=it.get("title") or it.get("displayTitle") or "",
            price=price,
            published_at=None,
            description=it.get("description") or it.get("categorySpecificDescription") or "",
            city=loc.get("cityName"),
            zipcode=None,
            department=None,
            lat=_f(loc.get("latitude")),
            lng=_f(loc.get("longitude")),
            country=(loc.get("countryAbbreviation") or "BE").upper(),
            seller_id=str(seller.get("sellerId")) if seller.get("sellerId") else None,
            image_urls=tuple(_images(it)),
            search_name=search_name,
        )


def _with_offset(url: str, offset: int) -> str:
    if "offset=" in url:
        return re.sub(r"offset=\d+", f"offset={offset}", url)
    return url + ("&" if "?" in url else "?") + f"offset={offset}"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _images(it: dict) -> list[str]:
    urls = []
    for p in it.get("pictures") or []:
        if isinstance(p, dict) and p.get("url"):
            urls.append(p["url"])
    for u in it.get("imageUrls") or []:
        if isinstance(u, str):
            urls.append(u if u.startswith("http") else "https:" + u)
    return urls[:10]
