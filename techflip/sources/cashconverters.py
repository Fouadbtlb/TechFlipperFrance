"""Cash Converters Belgium - a pro second-hand chain, priced like a shop.

Worth its own source because it does not behave like a marketplace. A private
seller prices by hope and negotiates; a chain prices to clear stock on a
schedule and does not haggle, so its mistakes are systematic and repeatable
rather than one-off. The owner found a Steam Deck LCD at 230 and an OLED 2To at
500 there, which is well under the private asks this tool already tracks.

The site is PrestaShop 1.7, so `&ajax=1` on any category or search URL returns
clean JSON (`products[]` with id, name, price_amount, url, cover) instead of
HTML to parse.

Location is the useful part. Every item sits in one physical shop, and the
category facet filters by it (`q=Magasin-JAMBES`), so an entire page of results
shares a known town -- no per-product request needed to find out where it is.
JAMBES is Namur; SAMBREVILLE, HUY and WAVRE ring it. Store names are geocoded
through pgeocode's Belgian dataset rather than a table of coordinates typed out
by hand.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import urllib.parse

from curl_cffi import requests

from ..config import SearchConfig
from ..domain import Listing

log = logging.getLogger(__name__)

_BASE = "https://www.cashconverters.be"
_PER_PAGE = 48
_TAGS = re.compile(r"<[^>]+>")


class CashConvertersSource:
    name = "cashconverters"

    def __init__(self, impersonate: str = "chrome131", timeout: float = 30.0):
        self.session = requests.Session(impersonate=impersonate)
        self.timeout = timeout
        self._geo: dict[str, tuple[float, float] | None] = {}

    def fetch(self, search: SearchConfig, page: int = 1) -> list[Listing]:
        url = _with_ajax(search.url, page)
        r = self.session.get(url, timeout=self.timeout,
                             headers={"Accept": "application/json",
                                      "X-Requested-With": "XMLHttpRequest"})
        if "json" not in r.headers.get("content-type", ""):
            log.warning("cashconverters: non-JSON (HTTP %s) - blocked?", r.status_code)
            return []
        store = _store_of(search.url)
        latlng = self._latlng(store)
        out: list[Listing] = []
        for item in (r.json() or {}).get("products") or []:
            # `add_to_cart_url` is null exactly when the shop has sold the
            # item; `active` still reads 1, so it is no help. The 700 EUR
            # RTX 3080 at Ixelles was recommended as the buy of the weekend
            # while its own page said "Rupture de stock".
            if not item.get("add_to_cart_url"):
                continue
            try:
                out.append(self._normalize(item, search.name, store, latlng))
            except Exception:
                log.exception("cashconverters: normalization failed")
        return out

    def _normalize(self, it: dict, search_name: str, store, latlng) -> Listing:
        price = it.get("price_amount")
        return Listing(
            source=self.name,
            source_id=str(it.get("id_product")),
            url=it.get("url") or it.get("canonical_url") or _BASE,
            title=(it.get("name") or "").strip(),
            price=float(price) if price is not None else None,
            # A shop has stock, not a posting date. Recording the day we first
            # saw it is the closest true statement, and it is what lets the
            # resweep reconsider the item later instead of judging it once.
            published_at=dt.date.today().isoformat(),
            description=_TAGS.sub(" ", it.get("description_short") or "").strip(),
            city=_pretty(store),
            country="BE",
            owner_type="pro",
            lat=latlng[0] if latlng else None,
            lng=latlng[1] if latlng else None,
            image_urls=tuple(_images(it)),
            source_category=_category_of(it.get("url") or ""),
            search_name=search_name,
        )

    def _latlng(self, store: str | None):
        if not store:
            return None
        if store not in self._geo:
            self._geo[store] = _geocode(store)
        return self._geo[store]


def _with_ajax(url: str, page: int) -> str:
    parts = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    q.update({"ajax": "1", "resultsPerPage": str(_PER_PAGE), "page": str(page)})
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def _store_of(url: str) -> str | None:
    """The shop a filtered category page is pinned to, from `q=Magasin-XXX`."""
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    m = re.match(r"Magasin-(.+)$", q.get("q", ""))
    return m.group(1).strip() if m else None


def _pretty(store: str | None) -> str | None:
    return store.title() if store else None


def _geocode(store: str):
    try:
        import pgeocode
    except Exception:
        return None
    try:
        df = pgeocode.Nominatim("be").query_location(store.title(), top_k=1)
        if len(df):
            row = df.iloc[0]
            lat, lng = float(row["latitude"]), float(row["longitude"])
            if lat == lat and lng == lng:          # NaN when unknown
                return (lat, lng)
    except Exception:
        log.warning("cashconverters: geocoding failed for %r", store, exc_info=True)
    return None


def _category_of(url: str) -> str | None:
    """The aisle segment of a product URL: /fr/<aisle>/<id>-<slug>.html."""
    m = re.search(r"/fr/([a-z0-9-]+)/\d+-", url or "")
    return m.group(1) if m else None


def _images(it: dict) -> list[str]:
    sizes = ((it.get("cover") or {}).get("bySize") or {})
    urls = [v.get("url") for v in sizes.values() if isinstance(v, dict) and v.get("url")]
    return urls[-1:] or urls
