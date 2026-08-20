"""Dead links are how a deal tool loses the person using it.

Two of the three best PS5s the board offered had been gone for weeks. Nothing
had ever checked: `status` and `disappeared_at` were in the schema from day one
with no code path writing to them.
"""
from techflip.domain import Listing
from techflip.liveness import query_for, verify
from techflip.storage import Store


def _l(uid, title, price=250):
    return Listing(source="2ememain", source_id=uid, url="u", title=title,
                   price=price, published_at="2026-08-01", description="",
                   city="Menen", search_name="PS5")


class _Source:
    """Returns whatever the site would return for a query."""

    def __init__(self, by_query, boom=False):
        self.by_query, self.boom = by_query, boom
        self.queries = []

    def fetch(self, search, page=1):
        if self.boom:
            raise RuntimeError("DataDome")
        self.queries.append(search.name)
        ids = next((v for k, v in self.by_query.items() if k in search.url), [])
        return [_l(i, "whatever") for i in ids]


def test_a_listing_the_search_no_longer_returns_is_marked_gone(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "sony PlayStation ps5 model normal goede staat"))
    store.upsert_listing(_l("m2", "Valve Steam Deck OLED 512 Go"))

    src = _Source({"sony%20playstation%20ps5%20model": ["m9", "m8"],   # m1 absent
                   "valve%20steam%20deck%20oled": ["m2", "m7"]})       # m2 present
    stats = verify(store, {"2ememain": src}, ["2ememain:m1", "2ememain:m2"], pause=(0, 0))

    assert stats["results"] == {"2ememain:m1": "gone", "2ememain:m2": "alive"}
    assert {k: v for k, v in stats.items() if k != "results"} == {
        "checked": 2, "alive": 1, "gone": 1, "skipped": 0}
    st = store.statuses()
    assert st["2ememain:m1"] == "gone"
    assert st["2ememain:m2"] == "active"


def test_going_missing_records_how_long_it_took_to_sell(tmp_path):
    """first_seen -> disappeared_at is the only sold-side evidence available,
    and what the asking-price bias will eventually be measured against."""
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "Valve Steam Deck OLED 512 Go"))
    store.conn.execute("UPDATE listings SET first_seen = datetime('now','-6 days')")
    store.conn.commit()

    store.mark_gone("2ememain:m1")
    row = store.conn.execute(
        "SELECT status, disappeared_at, days_on_market FROM listings").fetchone()
    assert row["status"] == "gone"
    assert row["disappeared_at"] is not None
    assert 5.5 < row["days_on_market"] < 6.5


def test_a_blocked_source_never_declares_anything_dead(tmp_path):
    """A DataDome wall would otherwise wipe the whole board in one pass."""
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "Valve Steam Deck OLED 512 Go"))

    stats = verify(store, {"2ememain": _Source({}, boom=True)},
                   ["2ememain:m1"], pause=(0, 0))
    assert stats["gone"] == 0 and stats["skipped"] == 1
    assert store.statuses()["2ememain:m1"] == "active"
    # And it must not be reported as confirmed either: unchecked is its own
    # answer, distinct from alive.
    assert stats["results"]["2ememain:m1"] == "skipped"


def test_the_query_keeps_only_identifying_words():
    assert query_for("Valve Steam Deck OLED 512 Go") == "valve steam deck oled"
    assert query_for("PS5 en tres bon etat, a vendre urgent") == "ps5"
    # Order preserved: a relevance ranker reads "steam deck oled", not a bag.
    # Bare digits are dropped: "3" identifies nothing on its own.
    assert query_for("Nintendo Switch OLED avec 3 jeux") == "nintendo switch oled jeux"


def test_an_untitled_or_unknown_listing_is_skipped_not_killed(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "de la le"))          # nothing identifying
    src = _Source({})
    stats = verify(store, {"2ememain": src}, ["2ememain:m1", "2ememain:nope"],
                   pause=(0, 0))
    assert stats["skipped"] == 2 and stats["gone"] == 0
    assert src.queries == []
