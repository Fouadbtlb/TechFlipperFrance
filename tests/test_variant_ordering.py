"""A cheaper model can never be worth more than the model it is cut down from.

Pinning real sold prices (PS5 = 340) while the Digital kept its scraped asking
median (345) made the Digital worth MORE than the disc console it is a cheaper
version of. That is impossible, and it is the kind of nonsense that turns into a
phantom margin on the very ads the tool is most confident about.

The ordering comes from the pricebook's own seeds, so it needs no new table: if
the catalog says a Digital seeds below a PS5, no amount of scraping may invert
them.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker

CATALOG = load_catalog("config/pricebook.yaml")


class _Store:
    def __init__(self, prices):
        self.prices = prices

    def component_prices(self, key, since_iso, stale_days=None):
        return self.prices.get(key, [])


def test_a_digital_ps5_cannot_outvalue_a_disc_ps5():
    store = _Store({"console:ps5-digital": [345] * 6})
    t = PriceTracker(store, CATALOG, 5, 90, sold={"console:ps5": 340})
    assert t.price("console:ps5").unit_value == 340
    assert t.price("console:ps5-digital").unit_value <= 340


def test_a_cheaper_variant_keeps_its_own_price_when_already_below():
    store = _Store({"console:ps5-digital": [290] * 6})
    t = PriceTracker(store, CATALOG, 5, 90, sold={"console:ps5": 340})
    assert t.price("console:ps5-digital").unit_value == 290


def test_a_switch_lite_cannot_outvalue_a_switch():
    store = _Store({"console:switch-lite": [400] * 6, "console:switch": [160] * 6})
    t = PriceTracker(store, CATALOG, 5, 90)
    lite = t.price("console:switch-lite").unit_value
    full = t.price("console:switch").unit_value
    assert lite <= full, f"Lite {lite} > Switch {full}"


def test_a_pricier_variant_is_left_alone():
    """Switch OLED really is worth more than a Switch; the rule reads the
    catalog's seed ordering and so does not touch it."""
    store = _Store({"console:switch-oled": [300] * 6, "console:switch": [160] * 6})
    t = PriceTracker(store, CATALOG, 5, 90)
    assert t.price("console:switch-oled").unit_value == 300


def test_unrelated_components_are_never_compared():
    store = _Store({"gpu:rtx-3060": [250] * 6})
    t = PriceTracker(store, CATALOG, 5, 90, sold={"console:ps5": 340})
    assert t.price("gpu:rtx-3060").unit_value == 250
