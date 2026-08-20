from techflip.domain import Listing
from techflip.storage import Store


def _l(published_at, price=100):
    return Listing(
        source="2ememain", source_id="1", url="u", title="Steam Deck OLED 512 Go",
        price=price, published_at=published_at, description="", city="Gent",
        search_name="Steam Deck",
    )


def test_upsert_backfills_a_missing_date_without_ever_clearing_one(tmp_path):
    store = Store(tmp_path / "t.db")

    store.upsert_listing(_l(None))                       # stored before dates parsed
    assert _published(store) is None

    store.upsert_listing(_l("2026-08-11"))               # re-fetched, date now read
    assert _published(store) == "2026-08-11"

    store.upsert_listing(_l(None, price=90))             # a later blank must not wipe it
    assert _published(store) == "2026-08-11"
    assert store.conn.execute("SELECT price FROM listings").fetchone()["price"] == 90


def _published(store):
    return store.conn.execute("SELECT published_at FROM listings").fetchone()["published_at"]


def test_a_price_cut_is_recorded_and_kept(tmp_path):
    """`price_history` and `last_price` were designed for this and never wired
    up: the upsert wrote `last_price = excluded.price`, so it always equalled
    the current price and no drop could ever be seen. A seller who has already
    cut their price is the clearest buy signal on a marketplace, and the only
    one that also tells you they will cut again."""
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("2026-08-11", price=350))
    store.upsert_listing(_l("2026-08-11", price=350))     # unchanged re-sighting
    store.upsert_listing(_l("2026-08-11", price=300))     # the cut

    row = store.conn.execute("SELECT price, last_price FROM listings").fetchone()
    assert (row["price"], row["last_price"]) == (300, 350)

    hist = [r["price"] for r in store.conn.execute(
        "SELECT price FROM price_history ORDER BY id")]
    assert hist == [350, 300], "the opening price and every change, no duplicates"

    drop = store.price_drop("2ememain:1")
    assert drop["first"] == 350 and drop["current"] == 300
    assert drop["cut"] == 50


def test_a_listing_that_never_moved_reports_no_drop(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("2026-08-11", price=350))
    store.upsert_listing(_l("2026-08-11", price=350))
    assert store.price_drop("2ememain:1") is None


def test_days_on_market_counts_from_the_first_sighting(tmp_path):
    """Still being returned by a search after a week is proof the ad has NOT
    sold, whatever the seller is asking. That is the one delisting signal we can
    trust: vanishing from page 1 only means newer ads pushed it down."""
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("2026-08-01", price=350))
    store.conn.execute("UPDATE listings SET first_seen = '2026-08-01T09:00:00+00:00', "
                       "last_seen = '2026-08-12T09:00:00+00:00'")
    store.conn.commit()
    assert store.days_on_market("2ememain:1") == 11.0
