"""`ingest` fills the pool from a searches file and writes nothing else.

The shopping board is only as good as the freshness of the pool, and the
scanner service is off. Refreshing it was a throwaway script that got lost
between sessions three times; it belongs in the CLI.

The contract that matters: ingest never alerts, never marks a listing gone,
and never touches the alerted bookkeeping. A diagnostic that stubbed the
notifier once burned fifteen real deals by marking them alerted without
sending them, and this path must not be able to repeat that.
"""
from techflip.config import SearchConfig
from techflip.pricing.catalog import load_catalog
from techflip.domain import Listing
from techflip.ingest import ingest
from techflip.storage import Store


class _Source:
    name = "fake"

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch(self, search, page=1):
        self.calls.append((search.name, page))
        return self.pages.get(page, [])


def _l(i, price=300.0):
    return Listing(source="fake", source_id=str(i), url=f"u{i}",
                   title="Console PS5 edition disque", price=price,
                   published_at="2026-09-17", description="", city="Lille")


def test_it_upserts_every_page_until_a_short_one(tmp_path):
    src = _Source({1: [_l(1), _l(2)], 2: [_l(3)]})
    store = Store(tmp_path / "t.db")
    s = SearchConfig(name="s", url="u", source="fake", min_price=50)
    stats = ingest(store, [s], {"fake": src}, max_pages=5, per_page=2, sleep=0)
    assert stats["kept"] == 3 and stats["new"] == 3
    assert [p for _, p in src.calls] == [1, 2]


def test_prices_outside_the_search_band_are_skipped(tmp_path):
    src = _Source({1: [_l(1, 10.0), _l(2, 300.0), _l(3, 9000.0)]})
    store = Store(tmp_path / "t.db")
    s = SearchConfig(name="s", url="u", source="fake", min_price=50, max_price=1000)
    assert ingest(store, [s], {"fake": src}, max_pages=1, sleep=0)["kept"] == 1


def test_it_records_the_recognized_component_so_the_tracker_can_learn(tmp_path):
    src = _Source({1: [_l(1)]})
    store = Store(tmp_path / "t.db")
    s = SearchConfig(name="s", url="u", source="fake", min_price=50)
    ingest(store, [s], {"fake": src}, catalog=load_catalog("config/pricebook.yaml"),
           max_pages=1, sleep=0)
    row = store.conn.execute(
        "SELECT primary_component FROM listings WHERE uid='fake:1'").fetchone()
    assert row["primary_component"] == "console:ps5"


def test_a_failing_source_costs_one_search_not_the_run(tmp_path):
    class _Boom(_Source):
        def fetch(self, search, page=1):
            raise RuntimeError("datadome")

    store = Store(tmp_path / "t.db")
    searches = [SearchConfig(name="bad", url="u", source="boom", min_price=1),
                SearchConfig(name="ok", url="u", source="fake", min_price=1)]
    stats = ingest(store, searches, {"boom": _Boom({}), "fake": _Source({1: [_l(1)]})},
                   max_pages=1, sleep=0)
    assert stats["errors"] == 1 and stats["kept"] == 1


def test_it_never_marks_anything_alerted_or_gone(tmp_path):
    store = Store(tmp_path / "t.db")
    s = SearchConfig(name="s", url="u", source="fake", min_price=50)
    ingest(store, [s], {"fake": _Source({1: [_l(1)]})}, max_pages=1, sleep=0)
    n = store.conn.execute(
        "SELECT COUNT(*) c FROM alerts WHERE uid='fake:1'").fetchone()["c"]
    status = store.conn.execute(
        "SELECT status FROM listings WHERE uid='fake:1'").fetchone()["status"]
    assert n == 0 and (status or "") != "gone"
