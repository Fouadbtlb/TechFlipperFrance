"""Cash Express: the same pro-chain logic as Cash Converters, one street away.

LILLE CENTRE is 1 km from home and LIEVIN 29 km; ANDENNE and HORNU sit on the
Namur road. That is closer than anything else this tool watches, so a 30 EUR
margin there is worth more than a 100 EUR margin in Arlon.

Three things this source has that Cash Converters does not:
  - `created_at`, a real per-item date, so "just put on the shelf" is knowable;
  - exact shop coordinates published by the site itself, so no name-guessing;
  - `categories_faceting`, a clean shelf label that feeds the aisle guard.
"""


from techflip.config import SearchConfig
from techflip.sources.cashexpress import SHOPS, CashExpressSource, _index_for, _shelf

HIT = {
    "objectID": "637839",
    "label": "Ordinateur portable core i5-8265 ideapad c340 512go 8go",
    "brand": {"label": "LENOVO"},
    "price_tax_incl": 252.99,
    "shop_label": "LILLE CENTRE",
    "shop_country": "FR",
    "quantity": 1,
    "created_at": 1788220800,          # 2026-09-01
    "url": "https://www.cashexpress.fr/p-219745/637839/lenovo-ideapad",
    "product_image": "https://www.cashexpress.fr/uploaded/x.jpg",
    "categories_faceting": [{"id": 1, "label": "PC portables"}],
    "universe": "Informatique",
    "Processeur": "Intel i5",
    "Mémoire RAM": "8 Go",
}

SOLD = dict(HIT, objectID="999", label="Manette ps5", quantity=0,
            categories_faceting=[{"id": 2, "label": "Accessoires gaming"}])


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append((url, json))
        return _Resp({"hits": [HIT, SOLD], "nbHits": 2, "nbPages": 1})


class _Resp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _source():
    s = CashExpressSource()
    s.session = _Session()
    return s


def _search(url):
    return SearchConfig(name="CE Lille", url=url, source="cashexpress")


URL = ("https://www.cashexpress.fr/produits-occasions.html"
       "?shop=LILLE+CENTRE&shelf=PC+portables&min=100")


# --- normalization -------------------------------------------------------

def test_a_hit_becomes_a_listing_placed_at_its_shop():
    got = _source().fetch(_search(URL))
    assert len(got) == 1                       # the qty-0 controller is dropped
    l = got[0]
    assert l.uid == "cashexpress:637839"
    assert l.price == 252.99
    assert l.city == "Lille Centre"
    assert l.country == "FR"
    assert l.owner_type == "pro"
    assert (round(l.lat, 2), round(l.lng, 2)) == (50.64, 3.07)
    assert l.published_at == "2026-09-01"


def test_the_brand_is_put_back_into_the_title():
    """The label says "ideapad c340", never "Lenovo": the extractor needs both."""
    l = _source().fetch(_search(URL))[0]
    assert l.title.lower().startswith("lenovo")
    assert "ideapad" in l.title.lower()


def test_spec_attributes_become_description_text():
    """Structured features are the one thing a shop gives that a seller does not."""
    l = _source().fetch(_search(URL))[0]
    assert "Intel i5" in l.description and "8 Go" in l.description


def test_out_of_stock_is_dropped():
    """Cash Converters taught this: a sold item still reads as a live product."""
    assert all(l.source_id != "999" for l in _source().fetch(_search(URL)))


def test_the_shelf_label_feeds_the_aisle_guard():
    from techflip.hunt import _aisle_bars_machines
    assert _shelf(HIT) == "pc-portables"
    assert not _aisle_bars_machines(_shelf(HIT))
    assert _aisle_bars_machines(_shelf(SOLD))          # "accessoires-gaming"


def test_the_universe_is_never_the_aisle():
    """"Consoles & Jeux vidéo" contains "jeux": using it would bar every console."""
    from techflip.hunt import _aisle_bars_machines
    hit = dict(HIT, categories_faceting=[{"label": "Consoles"}],
               universe="Consoles & Jeux vidéo")
    assert not _aisle_bars_machines(_shelf(hit))


# --- query construction --------------------------------------------------

def test_the_search_url_becomes_algolia_facet_filters():
    src = _source()
    src.fetch(_search(URL))
    url, body = src.session.calls[0]
    assert "cashexpress_products_prod_fr" in url
    assert ["shop_label:LILLE CENTRE"] in body["facetFilters"]
    assert ["categories_faceting.label:PC portables"] in body["facetFilters"]
    assert "price_tax_incl>=100" in body["numericFilters"]


def test_algolia_pages_are_zero_based():
    """The pipeline asks for page 1 first; Algolia's first page is 0."""
    src = _source()
    src.fetch(_search(URL), page=1)
    src.fetch(_search(URL), page=3)
    assert [b["page"] for _, b in src.session.calls] == [0, 2]


def test_the_belgian_site_uses_the_belgian_index():
    assert _index_for("https://www.cashexpress.be/x") .endswith("_be")
    assert _index_for("https://www.cashexpress.fr/x").endswith("_fr")


# --- the shop table ------------------------------------------------------

def test_shops_are_the_sites_own_coordinates_not_a_name_guess():
    """pgeocode's name search puts LILLE CENTRE in Lillebonne, 250 km away."""
    from techflip.geo import LILLE, haversine
    assert haversine(*LILLE, SHOPS["LILLE CENTRE"]["lat"],
                     SHOPS["LILLE CENTRE"]["lng"]) < 3
    assert haversine(*LILLE, SHOPS["LIEVIN"]["lat"],
                     SHOPS["LIEVIN"]["lng"]) < 35


def test_the_namur_road_shops_are_present():
    assert SHOPS["ANDENNE"]["country"] == "BE"
    assert SHOPS["HORNU"]["country"] == "BE"


def test_an_unknown_shop_leaves_the_listing_unplaced_rather_than_wrong():
    src = _source()
    hit = dict(HIT, shop_label="NOWHERE")
    src.session.post = lambda u, json=None, **k: _Resp({"hits": [hit]})
    l = src.fetch(_search(URL))[0]
    assert l.lat is None and l.lng is None


def test_several_shops_in_one_search_mean_either_shop():
    """Algolia ORs inside an array and ANDs between them. One array per shop
    would ask for an item that is in Lille and Lievin at the same time."""
    from techflip.sources.cashexpress import _body
    body = _body("https://www.cashexpress.fr/x?shop=LILLE+CENTRE%7CLIEVIN"
                 "&shelf=PC+gamer", page=1)
    assert ["shop_label:LILLE CENTRE", "shop_label:LIEVIN"] in body["facetFilters"]
    assert ["categories_faceting.label:PC gamer"] in body["facetFilters"]
    assert len(body["facetFilters"]) == 2
