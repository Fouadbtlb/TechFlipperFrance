"""The reference price must come from ads that moved, not ads that sat.

Every value in this tool is a median of ASKING prices. Overpriced ads never
sell, so they stay in the pool forever and keep voting; correctly priced ones
sell and stop voting. The median therefore drifts up toward what sellers wish
they could get -- Xbox Series X read 490 EUR against a 350 seed -- and the
margins computed from it are partly phantom.

An ad a search is still returning after a week has demonstrably NOT sold at
that price. That is the one delisting fact that can be trusted here: vanishing
from page 1 only means newer ads pushed it down, but still being there is proof
it is still for sale.
"""
import datetime as dt

from techflip.domain import Listing
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _add(store, uid, price, first_day, last_day):
    l = Listing(source="2ememain", source_id=uid, url="u", title="Xbox Series X",
                price=price, published_at="2026-08-01", description="",
                city="Gent", search_name="Xbox")
    store.upsert_listing(l)
    store.set_primary_component(l.uid, "console:xbox-series-x", True)
    store.conn.execute(
        "UPDATE listings SET first_seen=?, last_seen=?, fetched_at=? WHERE uid=?",
        (f"2026-08-{first_day:02d}T09:00:00+00:00",
         f"2026-08-{last_day:02d}T09:00:00+00:00",
         dt.datetime.now(dt.timezone.utc).isoformat(), l.uid))
    store.conn.commit()


def test_ads_that_sat_unsold_for_weeks_stop_setting_the_price(tmp_path):
    store = Store(tmp_path / "t.db")
    # The dear ones outnumber the cheap ones, which is the whole mechanism:
    # a cheap ad sells and leaves the pool after a sighting or two, an
    # overpriced one stays and keeps voting in every median from now on.
    for i, p in enumerate((300, 310, 320)):
        _add(store, f"quick{i}", p, 10, 11)
    for i, p in enumerate((500, 520, 530, 540, 560)):
        _add(store, f"stuck{i}", p, 1, 14)

    biased = PriceTracker(store, CATALOG, min_comparables=5, window_days=90)
    honest = PriceTracker(store, CATALOG, min_comparables=5, window_days=90,
                          stale_days=7)

    assert biased.price("console:xbox-series-x").unit_value > 400
    assert honest.price("console:xbox-series-x").unit_value < 330


def test_the_debias_never_empties_the_pool(tmp_path):
    """If every comparable has been sitting, dropping them all would fall back
    to the seed and lose the only market evidence there is. Better a biased
    median than none, so the filter yields rather than starving the tracker."""
    store = Store(tmp_path / "t.db")
    for i, p in enumerate((520, 540, 560, 500, 530)):
        _add(store, f"stuck{i}", p, 1, 14)

    t = PriceTracker(store, CATALOG, min_comparables=5, window_days=90, stale_days=7)
    q = t.price("console:xbox-series-x")
    assert q.unit_value == 530 and q.n == 5


def test_off_by_default_so_the_alert_path_is_unchanged(tmp_path):
    store = Store(tmp_path / "t.db")
    for i, p in enumerate((520, 540, 560, 500, 530)):
        _add(store, f"stuck{i}", p, 1, 14)
    assert PriceTracker(store, CATALOG, 5, 90).price("console:xbox-series-x").n == 5
