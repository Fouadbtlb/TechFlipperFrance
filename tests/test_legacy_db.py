"""A database made by an older TechFlip opens on the current one.

The old `listings` table had no `margin` column; the schema step skipped the
existing table and then failed on its index, so nothing could start.
"""
import sqlite3

from techflip.storage import Store

_OLD = """
CREATE TABLE listings (uid TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
    title TEXT, price REAL, raw_json TEXT, first_seen TEXT, last_seen TEXT,
    status TEXT DEFAULT 'active', true_value REAL, net_profit REAL, primary_component TEXT);
CREATE TABLE price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL, price REAL, seen_at TEXT);
CREATE TABLE alerts (uid TEXT PRIMARY KEY, alerted_at TEXT, true_value REAL);
CREATE TABLE picks (uid TEXT PRIMARY KEY, state TEXT NOT NULL, note TEXT);
INSERT INTO listings (uid, source, source_id, title, price, raw_json, first_seen, last_seen)
    VALUES ('cashconverters:1', 'cashconverters', '1', 'Xbox Series X', 300, '{}', '2026-10-01', '2026-10-20');
"""


def test_an_old_database_opens_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(_OLD)
    con.close()

    store = Store(path)
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(listings)")}
    assert "margin" in cols
    row = store.conn.execute("SELECT title, price FROM listings").fetchone()
    assert (row["title"], row["price"]) == ("Xbox Series X", 300)


def test_a_fresh_database_still_builds(tmp_path):
    store = Store(tmp_path / "new.db")
    assert store.conn.execute("SELECT count(*) FROM listings").fetchone()[0] == 0
