"""Prices the user has actually achieved beat any median of asking prices.

Everything this tool calls "value" is a median of what sellers ASK. The owner
sells a Series X at 300 and a PS5 at 340; the scraped medians said 414 and 368.
Asking medians are the weakest evidence available and were being treated as the
strongest, so a real transaction price has to win outright.

A sold price is already what you receive, so the realization haircut must NOT be
applied on top of it -- that would discount the same money twice.
"""
from techflip.pricing.appraise import Item, appraise
from techflip.pricing.catalog import load_catalog
from techflip.pricing.sold import load_sold
from techflip.pricing.tracker import PriceTracker

CATALOG = load_catalog("config/pricebook.yaml")


class _Store:
    def __init__(self, prices):
        self.prices = prices

    def component_prices(self, key, since_iso, exclude_uid=None, stale_days=None):
        return self.prices.get(key, [])

    def sold_prices(self, key, since_iso, exclude_uid=None):
        return []

    def days_to_sell(self, key, since_iso):
        return []

    def feedback_factor(self, key, since_iso):
        return 1.0


def test_a_sold_price_overrides_the_scraped_median():
    store = _Store({"console:ps5": [400, 410, 420, 430, 440, 450]})
    plain = PriceTracker(store, CATALOG, 5, 90)
    known = PriceTracker(store, CATALOG, 5, 90, owner_sales={"console:ps5": 340})

    assert plain.price("console:ps5").unit_value > 400
    q = known.price("console:ps5")
    assert q.unit_value == 340 and q.source == "owner"


def test_a_sold_price_is_not_discounted_a_second_time():
    """340 is what lands in your pocket, not a shop-window price."""
    store = _Store({})
    t = PriceTracker(store, CATALOG, 5, 90, owner_sales={"console:ps5": 340})
    appr = appraise([Item("console:ps5", 1, "working", "PS5", "console")], t)
    assert appr.true_value == 340, "console REALIZATION (0.92) must not apply"


def test_a_scraped_price_is_still_discounted_normally():
    store = _Store({"console:ps5": [400, 400, 400, 400, 400, 400]})
    t = PriceTracker(store, CATALOG, 5, 90)
    appr = appraise([Item("console:ps5", 1, "working", "PS5", "console")], t)
    assert appr.true_value == 368.0          # 400 * 0.92, unchanged


def test_a_broken_item_still_loses_value_even_at_a_known_price():
    store = _Store({})
    t = PriceTracker(store, CATALOG, 5, 90, owner_sales={"console:ps5": 340})
    appr = appraise([Item("console:ps5", 1, "broken", "PS5", "console")], t)
    assert appr.true_value == round(340 * 0.35, 2)


def test_components_with_no_sold_price_are_untouched():
    store = _Store({"gpu:rtx-3060": [250, 250, 250, 250, 250, 250]})
    t = PriceTracker(store, CATALOG, 5, 90, owner_sales={"console:ps5": 340})
    q = t.price("gpu:rtx-3060")
    assert q.unit_value == 250 and q.source == "learned"


def test_the_ledger_file_loads_the_owners_real_prices():
    sold = load_sold("config/sold.yaml")
    assert sold["console:ps5"] == 340
    assert sold["console:xbox-series-x"] == 300
    assert sold["console:xbox-series-s"] == 160
