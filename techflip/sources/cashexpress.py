"""Cash Express — a second pro chain, and the closest stock this tool watches.

Cash Converters taught the lesson that a chain's mistakes are systematic rather
than one-off, and also the limit of it: a shop's shelf price is the retail
ceiling, not what a private seller can get, so a pro row never teaches a resale
price (see `Store.component_prices`). What makes Cash Express worth adding
anyway is distance. LILLE CENTRE is 1 km from home and LIEVIN 29 km; ANDENNE
and HORNU are on the Namur road. A 30 EUR margin down the street beats a 100
EUR margin in Arlon once fuel at 3 EUR/litre is paid.

The site runs its own search on Algolia and ships the public search-only key in
the page (`.const-algolia-parameter`), so the catalogue is a clean JSON query
away: 121k items in France, 29k in Belgium, 124 shops.

Three things the record carries that Cash Converters' does not:

  - `created_at`, a real per-item unix date. A chain has stock, not a posting
    date, but it does have a day it graded the item and put it out -- which is
    exactly when a mispriced machine is still on the shelf.
  - `shop_label` plus the site's own published shop coordinates. pgeocode's
    name search, used for the Belgian stores, puts "LILLE CENTRE" in
    Lillebonne, 250 km away; the store locator publishes exact lat/lng, so
    there is no reason to guess.
  - `categories_faceting`, the shelf the item sits on ("PC gamer", "Accessoires
    gaming"), which feeds the aisle guard directly. The `universe` field must
    NOT be used for that: "Consoles & Jeux vidéo" contains "jeux" and would bar
    every console in the catalogue.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
import urllib.parse
from pathlib import Path

import requests

from ..config import SearchConfig
from ..domain import Listing

log = logging.getLogger(__name__)

# Search-only credentials, as published in every page of the site for its own
# search box. They grant reads of the product index and nothing else.
_APP_ID = "OQP9WWQWF8"
_API_KEY = "d038ade4612e762047e7e4b5fefeabb9"
_INDEX = "cashexpress_products_prod_%s"
_HITS_PER_PAGE = 100

_SHOPS_PATH = Path(__file__).resolve().parents[2] / "config" / "cashexpress-shops.json"

# Spec fields worth reading into the description. The shop grades and types its
# stock, so these are facts, not a seller's claim -- and "core i5-8265" in the
# label alone never says how much RAM is in the machine.
_SPEC_KEYS = ("Processeur", "Mémoire RAM", "Capacité disque dur",
              "Capacité de stockage", "Taille écran", "Modèle", "Plateforme")


def _load_shops() -> dict[str, dict]:
    try:
        return json.loads(_SHOPS_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.warning("cashexpress: shop table unreadable at %s", _SHOPS_PATH,
                    exc_info=True)
        return {}


SHOPS = _load_shops()


class CashExpressSource:
    name = "cashexpress"

    # Plain `requests`, not curl_cffi. Every other source here talks to a
    # marketplace behind DataDome and needs a real browser's TLS fingerprint;
    # this one talks to Algolia's public REST API, which has no bot protection
    # and no reason to care who is asking. Impersonation would only add a
    # dependency the source does not use.
    def __init__(self, timeout: float = 30.0, proxy: str | None = None):
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.timeout = timeout

    def fetch(self, search: SearchConfig, page: int = 1) -> list[Listing]:
        index = _index_for(search.url)
        url = f"https://{_APP_ID}-dsn.algolia.net/1/indexes/{index}/query"
        r = self.session.post(
            url, json=_body(search.url, page), timeout=self.timeout,
            headers={"X-Algolia-API-Key": _API_KEY,
                     "X-Algolia-Application-Id": _APP_ID,
                     "Content-Type": "application/json"})
        try:
            payload = r.json() or {}
        except Exception:
            log.warning("cashexpress: non-JSON reply (HTTP %s)",
                        getattr(r, "status_code", "?"))
            return []
        out: list[Listing] = []
        for hit in payload.get("hits") or []:
            # A shop keeps the product page up after the item walks out. The
            # RTX 3080 at Cash Converters was recommended as the buy of the
            # weekend while its own page said "Rupture de stock"; here the
            # stock signal is `quantity`, and it is authoritative.
            if not _in_stock(hit):
                continue
            try:
                out.append(_normalize(hit, search.name))
            except Exception:
                log.exception("cashexpress: normalization failed")
        return out


def _normalize(hit: dict, search_name: str) -> Listing:
    shop = str(hit.get("shop_label") or "").strip()
    place = SHOPS.get(shop.upper())
    price = hit.get("price_tax_incl")
    if price is None:
        price = hit.get("price_payed")
    return Listing(
        source="cashexpress",
        source_id=str(hit.get("objectID")),
        url=hit.get("url") or "https://www.cashexpress.fr/",
        title=_title(hit),
        price=float(price) if price is not None else None,
        published_at=_listed_on(hit),
        description=_specs(hit),
        city=shop.title() or None,
        # The shop's country, not the site's: cashexpress.fr also lists the
        # overseas stores, and a Guadeloupe price is not a French market price.
        country=str(hit.get("shop_country") or "FR"),
        owner_type="pro",
        lat=place["lat"] if place else None,
        lng=place["lng"] if place else None,
        image_urls=tuple(u for u in [hit.get("product_image")] if u),
        source_category=_shelf(hit),
        search_name=search_name,
    )


def _in_stock(hit: dict) -> bool:
    q = hit.get("quantity")
    return True if q is None else _int(q) > 0


def _title(hit: dict) -> str:
    """Brand + label. The label is the shop's shorthand and routinely omits the
    make: "Ordinateur portable core i5-8265 ideapad c340" never says Lenovo,
    and the extractor needs it to recognize anything."""
    label = str(hit.get("label") or "").strip()
    brand = str(((hit.get("brand") or {}) if isinstance(hit.get("brand"), dict)
                 else {}).get("label") or "").strip()
    if brand and _fold(brand) not in _fold(label):
        return f"{brand} {label}".strip()
    return label


def _specs(hit: dict) -> str:
    parts = [f"{k}: {hit[k]}" for k in _SPEC_KEYS
             if isinstance(hit.get(k), str) and hit[k].strip()]
    return " · ".join(parts)


def _listed_on(hit: dict) -> str | None:
    ts = hit.get("created_at")
    if not isinstance(ts, (int, float)):
        return None
    return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).date().isoformat()


def _shelf(hit: dict) -> str | None:
    """The shelf, slugified, for the aisle guard: "Accessoires gaming" ->
    "accessoires-gaming", which bars the console its title names."""
    cats = hit.get("categories_faceting") or []
    for c in cats:
        label = (c.get("label") if isinstance(c, dict) else None) or ""
        if label.strip():
            return _slug(label)
    return None


def _index_for(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return _INDEX % ("be" if host.endswith(".be") else "fr")


def _body(url: str, page: int) -> dict:
    """A configured search URL -> one Algolia query.

    The YAML keeps a readable https URL pointing at the real site; the query
    string carries the facets. `shelf` is `categories_faceting.label` and is
    the precise one -- `universe` is a whole department and mostly noise.
    """
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query,
                                    keep_blank_values=True))
    # One array per parameter, because Algolia ORs within an array and ANDs
    # between them. `shop=LILLE CENTRE|LIEVIN` has to mean either shop; a list
    # of arrays would mean both at once and match nothing.
    facets: list[list[str]] = []
    for param, field in (("shop", "shop_label"),
                         ("shelf", "categories_faceting.label"),
                         ("universe", "universe"),
                         ("brand", "brand.label")):
        values = _values(q.get(param))
        if values:
            facets.append([f"{field}:{v}" for v in values])
    numeric: list[str] = []
    if q.get("min"):
        numeric.append(f"price_tax_incl>={q['min']}")
    if q.get("max"):
        numeric.append(f"price_tax_incl<={q['max']}")
    body: dict = {
        "query": q.get("q", ""),
        # Algolia counts pages from zero; the pipeline asks for page 1 first.
        "page": max(0, int(page) - 1),
        "hitsPerPage": _HITS_PER_PAGE,
    }
    if facets:
        body["facetFilters"] = facets
    if numeric:
        body["numericFilters"] = numeric
    return body


def _values(raw: str | None) -> list[str]:
    return [v.strip() for v in (raw or "").split("|") if v.strip()]


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", _fold(s))).strip("-")
