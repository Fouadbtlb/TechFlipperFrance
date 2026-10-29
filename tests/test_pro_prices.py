"""A shop's asking price is not what YOU can sell for.

Adding Cash Converters put 9331 shop listings into a pool that held ~3500
private ones, so the learned median drifted to the shop's shelf price. Measured:
a Nintendo Switch asks 170 at Cash Converters (n=174) and 128 between private
sellers (n=79). You sell as a private seller, so 128 is your number -- valuing
at 170 invents 42 EUR of margin on every Switch in the pool, and the shop's
own stock then looks like a bargain against a price only the shop can get.
"""
from techflip.domain import Listing
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _add(store, uid, price, owner):
    l = Listing(source="cashconverters" if owner == "pro" else "2ememain",
                source_id=uid, url="u", title="Nintendo Switch", price=price,
                published_at="2026-09-01", description="", city="Mons",
                owner_type=owner, search_name="s")
    store.upsert_listing(l)
    store.set_primary_component(l.uid, "console:switch", True)


def test_shop_stock_does_not_set_the_resale_price(tmp_path):
    store = Store(tmp_path / "t.db")
    for i, p in enumerate((165, 170, 170, 175, 180, 170, 170)):
        _add(store, f"pro{i}", p, "pro")
    for i, p in enumerate((120, 125, 128, 130, 135)):
        _add(store, f"priv{i}", p, None)

    t = PriceTracker(store, CATALOG, min_comparables=5, window_days=90)
    q = t.price("console:switch")
    assert q.unit_value == 128, f"learned {q.unit_value} instead of the private median"
    assert q.n == 5


def test_with_no_private_comparables_it_says_seed_not_shop_price(tmp_path):
    """Better the pricebook's estimate than a number only a shop can achieve."""
    store = Store(tmp_path / "t.db")
    for i, p in enumerate((165, 170, 170, 175, 180)):
        _add(store, f"pro{i}", p, "pro")
    q = PriceTracker(store, CATALOG, 5, 90).price("console:switch")
    assert q.source == "seed" and q.n == 0
