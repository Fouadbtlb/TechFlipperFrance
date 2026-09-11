"""2ememain.be source - Belgian marketplace (Adevinta), right next to Lille.

Clean JSON API (/lrp/api/search). Belgian listings carry real lat/lng, so the
Lille-distance zoning is exact with no postal database. Same canonical Listing
as every source; paste a 2ememain search-API URL per search in searches.yaml.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import unicodedata

from curl_cffi import requests

from ..config import SearchConfig
from ..domain import Listing

log = logging.getLogger(__name__)

_BASE = "https://www.2ememain.be"
_LIMIT = 30


class DeuxiemeMainSource:
    name = "2ememain"

    def __init__(self, impersonate: str = "chrome131", timeout: float = 25.0, proxy: str | None = None):
        self.session = requests.Session(impersonate=impersonate)
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
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
            published_at=_published_at(it.get("date")),
            description=it.get("description") or it.get("categorySpecificDescription") or "",
            source_category=_aisle_of(url),
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


# The API dates a listing the way the site shows it ("Hier", "6 aout 26"), in
# French or Dutch depending on the ad. Parsing it is what lets the resweep come
# back to a listing later: without a date every Belgian ad got exactly one
# evaluation, on the cycle it first appeared, and was never reconsidered.
_RELATIVE = {
    "aujourd hui": 0, "aujourdhui": 0, "vandaag": 0,
    "eergisteren": 2, "avant hier": 2,
    "gisteren": 1, "hier": 1,
}
_MONTHS = {
    "jan": 1, "feb": 2, "fev": 2, "mar": 3, "mrt": 3, "apr": 4, "avr": 4,
    "mai": 5, "mei": 5, "jun": 6, "jui": 7, "jul": 7, "aou": 8, "aug": 8,
    "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dec": 12,
}
_DMY = re.compile(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{2,4})")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _published_at(raw: str | None, today: dt.date | None = None) -> str | None:
    """ISO day for a 2ememain date label, or None when it cannot be read.

    Returned as YYYY-MM-DD so it compares directly against the resweep cutoff.
    """
    if not raw:
        return None
    today = today or dt.datetime.now(tz=dt.timezone.utc).date()
    t = _strip_accents(str(raw).lower()).replace("'", " ").replace("-", " ")
    t = " ".join(t.split())

    if ":" in t and not any(ch.isalpha() for ch in t):
        return today.isoformat()
    for word, back in _RELATIVE.items():
        if word in t:
            return (today - dt.timedelta(days=back)).isoformat()

    m = _DMY.search(t)
    if m:
        day, month_word, year = m.groups()
        month = _MONTHS.get(month_word[:3])
        if month:
            year = int(year)
            year += 2000 if year < 100 else 0
            try:
                return dt.date(year, month, int(day)).isoformat()
            except ValueError:
                return None
    return None


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


def _aisle_of(url: str) -> str | None:
    """The aisle the seller filed it under: /v/<department>/<aisle>/<id>-<slug>.

    Ground truth about the kind of thing for sale, exactly as on Cash
    Converters. 94 rows under /jeux-sony-playstation-5/ were each priced as a
    340 EUR console because this was being dropped on the floor.
    """
    m = re.search(r"/v/[a-z0-9-]+/([a-z0-9-]+)/m?\d", url or "")
    return m.group(1) if m else None
