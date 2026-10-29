"""The plumbing: migrations, retention, health, rate limiting, compression,
and the explicit exits of the valuation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from techflip import pipeline as pipe
from techflip.api.accounts import Accounts
from techflip.api.app import create_app
from techflip.api.services import RateLimiter
from techflip.config import SearchConfig, Settings
from techflip.db import add_column, connect, migrate
from techflip.domain import Listing
from techflip.storage import MIGRATIONS, Store
from techflip.valuation import Rejection
from tests.test_api import FakeRC, _api, _seed_deal, _settings

NOW = datetime.now(timezone.utc)


def test_migrations_run_once_and_new_steps_apply_alone(tmp_path):
    conn = connect(tmp_path / "m.db")
    assert migrate(conn, MIGRATIONS) == ["store/001_schema"]
    assert migrate(conn, MIGRATIONS) == []                      # nothing twice
    step = ("store/002_example", lambda c: add_column(c, "listings", "example", "TEXT"))
    assert migrate(conn, (*MIGRATIONS, step)) == ["store/002_example"]
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(listings)")}
    assert "example" in cols


def _listing(store, i, *, days_ago, status="active", single=False):
    seen = (NOW - timedelta(days=days_ago)).isoformat()
    l = Listing(source="leboncoin", source_id=str(i), url="u", title=f"Objet {i}", price=100,
                published_at=seen, fetched_at=seen)
    store.upsert_listing(l)
    if single:
        store.set_primary_component(l.uid, "gpu:rtx-4070", True)
    if status == "gone":
        store.mark_gone(l.uid, at=seen)
    return l.uid


def test_prune_drops_only_what_nothing_reads(tmp_path):
    s = Store(tmp_path / "t.db")
    old_gone = _listing(s, 1, days_ago=200, status="gone", single=True)
    old_noise = _listing(s, 2, days_ago=200)                      # never valued, never learned from
    old_comp = _listing(s, 3, days_ago=200, single=True)          # still teaches the tracker
    recent_gone = _listing(s, 4, days_ago=20, status="gone", single=True)
    fresh = _listing(s, 5, days_ago=1)

    removed = s.prune(keep_days=90)
    assert removed["listings"] == 2
    assert s.get(old_gone) is None and s.get(old_noise) is None
    assert s.price_points(old_gone) == []
    for uid in (old_comp, recent_gone, fresh):
        assert s.get(uid) is not None
    assert s.get(recent_gone)["raw_json"] is None                 # gone > 7 days: full JSON dropped
    assert s.get(fresh)["raw_json"] is not None


def test_account_bookkeeping_is_pruned(tmp_path):
    a = Accounts(tmp_path / "t.db")
    uid = a.create_user("dev", "d1")
    a.mark_notified(uid, ["x"])
    a.conn.execute("UPDATE notified SET sent_at=?", ((NOW - timedelta(days=40)).isoformat(),))
    a.conn.commit()
    a.prune()
    assert a.notified_uids(uid, ["x"]) == set()


def test_health_reports_scanner_freshness(tmp_path):
    settings = _settings(tmp_path)
    c = TestClient(create_app(settings, _api(), entitlements_http=FakeRC().client()))
    assert c.get("/v1/health").json()["scanner"]["stale"] is True    # never ran
    Store(settings.db_path).set_meta("scanner", {"fetched": 12})
    h = c.get("/v1/health").json()["scanner"]
    assert h["stale"] is False and h["last"] == {"fetched": 12}
    s = Store(settings.db_path)
    s.conn.execute("UPDATE meta SET updated_at=? WHERE key='scanner'", ((NOW - timedelta(hours=2)).isoformat(),))
    s.conn.commit()
    assert c.get("/v1/health").json()["scanner"]["stale"] is True


def test_rate_limiter_blocks_and_forgets_idle_users():
    rl = RateLimiter(per_minute=2, window_s=0.05)
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    import time
    time.sleep(0.06)
    assert rl.allow("a")
    rl._sweep(time.monotonic() + 1)
    assert rl._hits == {}


def test_large_responses_are_gzipped(tmp_path):
    settings = _settings(tmp_path)
    c = TestClient(create_app(settings, _api(), entitlements_http=FakeRC().client()))
    Store(settings.db_path).set_meta("scanner", {"note": "x" * 3000})
    r = c.get("/v1/health", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_cycle_records_a_heartbeat(tmp_path, monkeypatch):
    class Empty:
        name = "leboncoin"

        def fetch(self, search, page=1):
            return []

    settings = Settings(telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"), ai_url="",
                        searches=(SearchConfig(name="x", url="u"),))
    monkeypatch.setattr(pipe, "_make_source", lambda n, s: Empty())
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.run_once()
    beat = p.store.get_meta("scanner")
    assert beat["fetched"] == 0 and "updated_at" in beat
    assert p.store.get_meta("pruned")["day"] == datetime.now().date().isoformat()


def test_valuation_exits_are_explicit(tmp_path, monkeypatch):
    settings = Settings(telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"), ai_url="http://x",
                        searches=(SearchConfig(name="PS5", url="u", min_price=100, max_price=900),))
    monkeypatch.setattr(pipe, "_make_source", lambda n, s: None)
    p = pipe.Pipeline(settings)
    cheap = Listing(source="leboncoin", source_id="1", url="u", title="PS5", price=20, published_at="x",
                    zipcode="59000", search_name="PS5")
    v = p.valuer.value(cheap, [])
    assert isinstance(v, Rejection) and "min" in v.reason and not v.discard

    trade = Listing(source="leboncoin", source_id="2", url="u", title="PS5 edition disque", price=200,
                    published_at="2099-01-01", zipcode="59000", description="envoi possible", search_name="PS5")
    p.store.upsert_listing(trade)
    p.valuer.classify = lambda l: {"is_trade": True}
    _, comps = p._ingest(trade)
    assert p._evaluate(trade, comps) is False
    assert p.store.alert_tier(trade.uid) == "confirmed"          # discarded for good
    assert p.store.get(trade.uid)["appraisal"] is None


def test_seeded_deal_helper_still_valid(tmp_path):
    uid = _seed_deal(tmp_path / "t.db", "z")
    assert Store(tmp_path / "t.db").get(uid)["margin"] > 0


_OLD_SCHEMA = """
CREATE TABLE listings (uid TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
    search_name TEXT, url TEXT, title TEXT, price REAL, city TEXT, zipcode TEXT, owner_type TEXT,
    published_at TEXT, fetched_at TEXT, raw_json TEXT, first_seen TEXT, last_seen TEXT,
    status TEXT DEFAULT 'active', primary_component TEXT, true_value REAL, net_profit REAL);
CREATE TABLE price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL, price REAL, seen_at TEXT);
CREATE TABLE alerts (uid TEXT PRIMARY KEY, alerted_at TEXT, true_value REAL, net_profit REAL, tier TEXT);
CREATE TABLE picks (uid TEXT PRIMARY KEY, state TEXT NOT NULL, note TEXT, updated_at TEXT);
"""


def test_an_older_database_is_imported_facts_only(tmp_path):
    """Months of scraped prices are the slowest thing to rebuild, so they come
    over; the old valuations do not (the current rules redo them)."""
    import json
    import sqlite3

    from techflip.pricing.catalog import load_catalog
    from techflip.pricing.identify import teaching_key

    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript(_OLD_SCHEMA)
    ad = Listing(source="2ememain", source_id="7", url="u", title="Nintendo Switch OLED", price=180,
                 published_at="2026-09-01", lat=50.8, lng=3.2, fetched_at=NOW.isoformat())
    old.execute("INSERT INTO listings (uid, source, source_id, title, price, raw_json, first_seen, last_seen, "
                "fetched_at, primary_component, true_value, net_profit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ad.uid, "2ememain", "7", ad.title, 180, json.dumps(ad.to_dict()), NOW.isoformat(),
                 NOW.isoformat(), NOW.isoformat(), "console:switch", 999, 500))
    old.execute("INSERT INTO price_history (uid, price, seen_at) VALUES (?, 200, 'x'), (?, 180, 'y')",
                (ad.uid, ad.uid))
    old.execute("INSERT INTO alerts (uid, tier) VALUES (?, 'confirmed')", (ad.uid,))
    old.execute("INSERT INTO picks (uid, state, updated_at) VALUES (?, 'interested', 'z')", (ad.uid,))
    old.commit()
    old.close()

    store = Store(tmp_path / "new.db")
    got = store.import_from(tmp_path / "old.db")
    assert got == {"listings": 1, "price_history": 2, "alerts": 1, "picks": 1}
    row = store.get(ad.uid)
    assert row["true_value"] is None and row["net_profit"] is None       # no stale valuation
    assert row["lat"] == 50.8 and row["title_key"] == "nintendo switch oled"
    assert store.import_from(tmp_path / "old.db")["price_history"] == 0  # twice is harmless
    catalog = load_catalog("config/pricebook.yaml")
    assert store.retrack(lambda l: teaching_key(l, catalog))["scanned"] == 1
    assert store.get(ad.uid)["primary_component"] == "console:switch-oled"


def test_shop_items_are_not_rechecked_as_price_references(tmp_path):
    """A shop's item leaving says nothing about private resale prices, so it
    is not worth a request every two days."""
    s = Store(tmp_path / "t.db")
    for i, owner in (("p", None), ("s", "pro")):
        l = Listing(source="leboncoin", source_id=i, url="u", title="RTX 4070", price=450,
                    published_at="x", owner_type=owner,
                    fetched_at=(NOW - timedelta(days=5)).isoformat())
        s.upsert_listing(l)
        s.set_primary_component(l.uid, "gpu:rtx-4070", True)
    assert [r["uid"] for r in s.due_for_check(10, "leboncoin")] == ["leboncoin:p"]
