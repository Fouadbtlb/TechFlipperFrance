"""Cash Converters: a pro chain, so its mispricing is systematic and repeatable.

A private seller prices by hope and haggles; a shop prices to clear stock on a
schedule and does not. The owner found a Steam Deck LCD at 230 and an OLED 2To
at 500 there, well under the private asks already tracked.
"""
import datetime as dt

from techflip.config import SearchConfig
from techflip.sources.cashconverters import CashConvertersSource, _store_of, _with_ajax

RAW = {
    "products": [
        {"id_product": 1166384, "name": "Console Steam deck OLED 2TO ",
         "price_amount": 500.0, "url": "https://www.cashconverters.be/fr/x/1-a.html",
         "add_to_cart_url": "https://www.cashconverters.be/cart?add=1",
         "description_short": "<p>Tres bon <b>etat</b></p>",
         "cover": {"bySize": {"small_default": {"url": "https://img/s.jpg"},
                              "large_default": {"url": "https://img/l.jpg"}}}},
        {"id_product": 999, "name": "Steam deck LCD 64go", "price_amount": 230.0,
         "url": "https://www.cashconverters.be/fr/x/2-b.html",
         "add_to_cart_url": "https://www.cashconverters.be/cart?add=2"},
    ]
}


class _Resp:
    headers = {"content-type": "application/json; charset=utf-8"}
    status_code = 200

    def json(self):
        return RAW


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        return _Resp()


def _source():
    s = CashConvertersSource()
    s.session = _Session()
    return s


def _search(url):
    return SearchConfig(name="CC Jambes", url=url, source="cashconverters")


def test_products_become_listings_located_at_their_shop(belgian_postcodes):
    src = _source()
    got = src.fetch(_search(
        "https://www.cashconverters.be/fr/138-jeux-consoles-video?q=Magasin-JAMBES"))
    assert [l.price for l in got] == [500.0, 230.0]
    # The slug is appended to the retyped name on purpose: the clerk drops
    # words the URL keeps ("z flip 7" vs .../z-flip-7-fe-...). See test_cc_slug.
    assert got[0].title.startswith("Console Steam deck OLED 2TO")
    assert got[0].uid == "cashconverters:1166384"
    # JAMBES is Namur: an item there must not read as 130km away in Lille terms
    # by having no coordinates at all.
    assert got[0].city == "Jambes"
    assert got[0].lat is not None and 50.3 < got[0].lat < 50.6
    assert got[0].country == "BE" and got[0].owner_type == "pro"


def test_html_is_stripped_from_the_blurb():
    assert _source().fetch(_search("https://x/?q=Magasin-JAMBES"))[0].description == \
        "Tres bon  etat"


def test_the_largest_image_is_kept():
    assert _source().fetch(_search("https://x/?q=Magasin-JAMBES"))[0].image_urls == \
        ("https://img/l.jpg",)


def test_stock_is_dated_the_day_it_is_first_seen():
    """A shop has stock, not a posting date, and a listing with no date is
    invisible to the resweep forever."""
    got = _source().fetch(_search("https://x/?q=Magasin-JAMBES"))
    assert got[0].published_at == dt.datetime.now(tz=dt.timezone.utc).date().isoformat()


def test_an_unfiltered_page_has_no_pretend_location():
    got = _source().fetch(_search("https://www.cashconverters.be/fr/138-jeux"))
    assert got[0].city is None and got[0].lat is None


def test_pagination_and_json_are_requested():
    src = _source()
    src.fetch(_search("https://www.cashconverters.be/fr/138-jeux?q=Magasin-HUY"), page=3)
    url = src.session.urls[0]
    assert "ajax=1" in url and "page=3" in url and "resultsPerPage=48" in url
    assert "q=Magasin-HUY" in url.replace("%2B", "+").replace("Magasin-HUY", "Magasin-HUY")


def test_the_shop_is_read_from_the_facet_link():
    assert _store_of("https://x/fr/138-a?q=Magasin-LA+LOUVIERE") == "LA LOUVIERE"
    assert _store_of("https://x/fr/138-a") is None


def test_existing_query_params_survive():
    out = _with_ajax("https://x/fr/138-a?q=Magasin-JAMBES&order=product.price.asc", 2)
    assert "q=Magasin-JAMBES" in urllib_unquote(out)
    assert "order=product.price.asc" in urllib_unquote(out)


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote_plus(s)


def test_a_sold_item_is_not_an_offer():
    """`add_to_cart_url` is null exactly when the shop has sold it -- `active`
    still reads 1. The 700 EUR Corsair RTX 3080 at Ixelles was recommended as
    the buy of the weekend while its page said "Rupture de stock"."""
    src = _source()
    src.session = _SoldSession()
    got = src.fetch(_search("https://x/?q=Magasin-IXELLES"))
    assert [l.title for l in got] == ["En stock"]


class _SoldResp(_Resp):
    def json(self):
        return {"products": [
            {"id_product": 1, "name": "En stock", "price_amount": 100.0,
             "url": "u", "add_to_cart_url": "https://x/cart?add=1"},
            {"id_product": 2, "name": "Vendu", "price_amount": 100.0,
             "url": "u", "add_to_cart_url": None, "active": "1"},
        ]}


class _SoldSession(_Session):
    def get(self, url, **kw):
        self.urls.append(url)
        return _SoldResp()
