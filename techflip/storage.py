"""SQLite persistence.

Design intent: every listing ever seen is kept. This is not just dedupe —
it silently builds the price dataset that will train the future ML valuation
model, for free, from day one.

Tables:
- listings : full history of everything scraped (append-only, upsert on price change)
- alerts   : which listings we already alerted on (never alert twice)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import median

from .domain import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid            TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    search_name    TEXT,
    url            TEXT,
    title          TEXT,
    price          REAL,
    brand          TEXT,
    model          TEXT,
    condition      TEXT,
    city           TEXT,
    zipcode        TEXT,
    department     TEXT,
    country        TEXT,
    owner_type     TEXT,
    has_phone      INTEGER,
    seller_id      TEXT,
    est_min        INTEGER,
    est_max        INTEGER,
    price_rating   TEXT,
    published_at   TEXT,
    fetched_at     TEXT,
    comparable_key TEXT,
    raw_json       TEXT,
    first_seen     TEXT,
    last_seen      TEXT,
    status         TEXT DEFAULT 'active',
    disappeared_at TEXT,
    days_on_market REAL,
    last_price     REAL,
    true_value     REAL,
    net_profit     REAL,
    bundle_details TEXT,
    primary_component TEXT,
    is_single      INTEGER,
    zone           TEXT,
    confidence     REAL,
    distance_km    REAL
);
CREATE INDEX IF NOT EXISTS idx_listings_comp ON listings(comparable_key);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings(fetched_at);
CREATE INDEX IF NOT EXISTS idx_listings_primary ON listings(primary_component);

CREATE TABLE IF NOT EXISTS price_history (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    uid     TEXT NOT NULL,
    price   REAL,
    seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pricehist_uid ON price_history(uid);

CREATE TABLE IF NOT EXISTS alerts (
    uid        TEXT PRIMARY KEY,
    alerted_at TEXT DEFAULT (datetime('now')),
    true_value REAL,
    net_profit REAL,
    tier       TEXT DEFAULT 'confirmed'
);

-- The human's verdict on a listing, from the web board. Separate from `alerts`
-- on purpose: `alerts` is the bot's own bookkeeping (already pushed to the
-- phone), this is the shortlist you actually drive out for, and neither may
-- ever silence the other.
CREATE TABLE IF NOT EXISTS picks (
    uid        TEXT PRIMARY KEY,
    state      TEXT NOT NULL,          -- 'interested' | 'hidden'
    note       TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        # check_same_thread=False so the web board can serve requests from the
        # HTTP server's worker threads off one connection. Safe here and only
        # here: this build reports sqlite3.threadsafety == 3 (SQLITE_THREADSAFE=1,
        # serialized), so SQLite itself does the locking. Re-check on another
        # machine before assuming it still holds.
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        # The scanner loop and the web board now hold the file at the same time.
        # Without a timeout the loser of a write race raises "database is locked"
        # immediately, which in the loop means a dropped cycle.
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self):
        acols = {r["name"] for r in self.conn.execute("PRAGMA table_info(alerts)")}
        if "tier" not in acols:
            self.conn.execute(
                "ALTER TABLE alerts ADD COLUMN tier TEXT DEFAULT 'confirmed'"
            )
        lcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        for col, typ in (
            ("est_min", "INTEGER"), ("est_max", "INTEGER"), ("price_rating", "TEXT"),
            ("country", "TEXT"), ("primary_component", "TEXT"), ("is_single", "INTEGER"),
            ("zone", "TEXT"), ("confidence", "REAL"), ("distance_km", "REAL"),
        ):
            if col not in lcols:
                self.conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")
        self.conn.commit()

    # ---------- listings ----------

    def upsert_listing(self, l: Listing) -> bool:
        """Insert or refresh a listing. Returns True if it's new."""
        cur = self.conn.execute(
            "SELECT price FROM listings WHERE uid = ?", (l.uid,)
        )
        row = cur.fetchone()
        is_new = row is None
        # Every price this ad has ever shown. A seller who already cut once is
        # the clearest buy signal a marketplace gives you, and the only one that
        # also says they will cut again. The table existed from day one and
        # nothing ever wrote to it, so the signal was simply never available.
        if is_new or row["price"] != l.price:
            self.conn.execute(
                "INSERT INTO price_history (uid, price, seen_at) VALUES (?,?,?)",
                (l.uid, l.price, l.fetched_at),
            )

        self.conn.execute(
            """
            INSERT INTO listings (
                uid, source, source_id, search_name, url, title, price,
                brand, model, condition,
                city, zipcode, department, country, owner_type, has_phone, seller_id,
                est_min, est_max, price_rating,
                published_at, fetched_at, comparable_key, raw_json,
                first_seen, last_seen, status, last_price
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(uid) DO UPDATE SET
                price = excluded.price,
                url = excluded.url,
                fetched_at = excluded.fetched_at,
                country = excluded.country,
                est_min = excluded.est_min,
                est_max = excluded.est_max,
                price_rating = excluded.price_rating,
                comparable_key = excluded.comparable_key,
                raw_json = excluded.raw_json,
                -- Fill a missing date in, never overwrite a known one with NULL.
                -- Rows stored before the source learned to read 2ememain's date
                -- label stay invisible to the resweep until this backfills them.
                published_at = COALESCE(excluded.published_at, listings.published_at),
                last_seen = excluded.last_seen,
                -- The PREVIOUS price, not the new one. Writing excluded.price
                -- here meant last_price always equalled price, so no drop was
                -- ever visible. An unchanged sighting must not erase the last
                -- real cut either, hence the CASE.
                last_price = CASE WHEN excluded.price IS NOT listings.price
                                  THEN listings.price ELSE listings.last_price END,
                status = 'active',
                disappeared_at = NULL,
                days_on_market = NULL
            """,
            (
                l.uid, l.source, l.source_id, l.search_name, l.url, l.title,
                l.price, l.brand, l.model, l.condition,
                l.city, l.zipcode, l.department, l.country, l.owner_type,
                int(l.has_phone), l.seller_id, l.est_min, l.est_max, l.price_rating,
                l.published_at, l.fetched_at,
                l.comparable_key(), json.dumps(l.to_dict(), ensure_ascii=False),
                l.fetched_at, l.fetched_at, "active", l.price
            ),
        )
        self.conn.commit()
        return is_new

    def update_tech_score(
        self, uid: str, true_value: float, net_profit: float, bundle_details: dict,
        zone: str | None = None, confidence: float | None = None,
        distance_km: float | None = None,
    ):
        self.conn.execute(
            "UPDATE listings SET true_value=?, net_profit=?, bundle_details=?, "
            "zone=?, confidence=?, distance_km=? WHERE uid=?",
            (true_value, net_profit, json.dumps(bundle_details, ensure_ascii=False),
             zone, confidence, distance_km, uid),
        )
        self.conn.commit()

    def set_primary_component(self, uid: str, primary: str | None, is_single: bool):
        self.conn.execute(
            "UPDATE listings SET primary_component=?, is_single=? WHERE uid=?",
            (primary, int(is_single), uid),
        )
        self.conn.commit()

    def component_prices(self, key: str, since_iso: str,
                         stale_days: float | None = None) -> list[float]:
        """Prices of single-item listings for one component, in the recency
        window. This is what the price tracker learns from.

        `stale_days` drops ads a search was still returning that many days after
        first sighting. They have demonstrably not sold at that price, and
        leaving them in is what makes the median mean "what sellers ask" rather
        than "what things go for".
        """
        # Private sellers only. A shop's shelf price is the retail ceiling,
        # not what you can get for the same item: a Switch asks 170 at Cash
        # Converters and 128 between private sellers. You sell as a private
        # seller. Pooling the two (9331 shop rows against ~3500 private)
        # dragged every median up to the shelf price and invented margin on
        # the shop's own stock.
        sql = ("SELECT price FROM listings WHERE primary_component=? "
               "AND price IS NOT NULL AND fetched_at >= ? "
               "AND (owner_type IS NULL OR owner_type != 'pro')")
        params: list = [key, since_iso]
        if stale_days is not None:
            sql += (" AND (first_seen IS NULL OR last_seen IS NULL "
                    "OR julianday(last_seen) - julianday(first_seen) < ?)")
            params.append(stale_days)
        return [r["price"] for r in self.conn.execute(sql, params)]

    def comparables(
        self,
        l: Listing,
    ) -> list[float]:
        """Prices of comparable listings (same key).
        Excludes the listing itself.
        """
        key = l.comparable_key()
        if key is None:
            return []

        clauses = ["comparable_key = ?", "uid != ?", "price IS NOT NULL"]
        params: list = [key, l.uid]

        rows = self.conn.execute(
            f"SELECT price FROM listings WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        return [r["price"] for r in rows]

    # ---------- alerts ----------

    def already_alerted(self, uid: str) -> bool:
        return self.alert_tier(uid) is not None

    def alert_tier(self, uid: str) -> str | None:
        """None = jamais alertée · 'tentative' = alertée sur preuve maigre ·
        'confirmed' = alertée sur estimation solide."""
        row = self.conn.execute(
            "SELECT tier FROM alerts WHERE uid = ?", (uid,)
        ).fetchone()
        return (row["tier"] or "confirmed") if row else None

    def mark_alerted(
        self, uid: str, true_value: float | None = None, net_profit: float | None = None,
        tier: str = "confirmed",
    ):
        self.conn.execute(
            "INSERT OR REPLACE INTO alerts (uid, true_value, net_profit, tier) "
            "VALUES (?,?,?,?)",
            (uid, true_value, net_profit, tier),
        )
        self.conn.commit()

    def recent_unalerted(self, since_iso: str) -> list:
        """Recent listings we never alerted on — candidates for re-scoring
        once the market DB has matured enough to judge them."""
        return self.conn.execute(
            """SELECT l.raw_json, l.search_name FROM listings l
               LEFT JOIN alerts a ON a.uid = l.uid
               WHERE a.uid IS NULL AND l.published_at >= ?""",
            (since_iso,),
        ).fetchall()

    def recompute_comparable_keys(self) -> int:
        """Re-derive comparable_key for every stored row (run after the key
        logic evolves — e.g. trim detection added)."""
        rows = self.conn.execute("SELECT uid, raw_json FROM listings").fetchall()
        for r in rows:
            l = Listing.from_dict(json.loads(r["raw_json"]))
            self.conn.execute(
                "UPDATE listings SET comparable_key = ? WHERE uid = ?",
                (l.comparable_key(), r["uid"]),
            )
        self.conn.commit()
        return len(rows)

    def mark_gone(self, uid: str):
        """This ad is no longer for sale. Records WHEN, which is the whole
        point: first_seen to disappeared_at is how long it took to sell, and
        that is the only sold-side evidence this tool can ever collect."""
        self.conn.execute(
            "UPDATE listings SET status='gone', disappeared_at=datetime('now'), "
            "days_on_market = julianday('now') - julianday(first_seen) "
            "WHERE uid = ?", (uid,))
        self.conn.commit()

    def mark_alive(self, uid: str):
        self.conn.execute(
            "UPDATE listings SET status='active', disappeared_at=NULL, "
            "last_seen=datetime('now') WHERE uid = ?", (uid,))
        self.conn.commit()

    def statuses(self) -> dict:
        return {r["uid"]: r["status"] for r in
                self.conn.execute("SELECT uid, status FROM listings")}

    def price_drop(self, uid: str) -> dict | None:
        """Opening price vs current, when the seller has cut it. None otherwise.

        Only cuts count. A price that went UP is a seller testing the market,
        not an opportunity, and averaging it in would hide the real cuts.
        """
        rows = [r["price"] for r in self.conn.execute(
            "SELECT price FROM price_history WHERE uid = ? AND price IS NOT NULL "
            "ORDER BY id", (uid,))]
        if len(rows) < 2 or rows[0] <= rows[-1]:
            return None
        return {"first": rows[0], "current": rows[-1],
                "cut": round(rows[0] - rows[-1], 2),
                "pct": round((rows[0] - rows[-1]) / rows[0], 3),
                "changes": len(rows) - 1}

    def days_on_market(self, uid: str) -> float | None:
        row = self.conn.execute(
            "SELECT julianday(last_seen) - julianday(first_seen) d "
            "FROM listings WHERE uid = ?", (uid,)).fetchone()
        return round(row["d"], 2) if row and row["d"] is not None else None

    def market_ages(self) -> dict:
        """uid -> days between first and last sighting, for the whole pool.

        One query instead of one per listing: the board prices ~2000 rows at a
        time and a per-row lookup turns a 2s scan into a minute.
        """
        return {r["uid"]: round(r["d"], 2) for r in self.conn.execute(
            "SELECT uid, julianday(last_seen) - julianday(first_seen) d FROM listings "
            "WHERE first_seen IS NOT NULL AND last_seen IS NOT NULL")
            if r["d"] is not None}

    def price_drops(self) -> dict:
        """uid -> drop dict, for every listing whose seller has cut the price."""
        out: dict[str, dict] = {}
        seq: dict[str, list] = {}
        for r in self.conn.execute(
                "SELECT uid, price FROM price_history WHERE price IS NOT NULL ORDER BY id"):
            seq.setdefault(r["uid"], []).append(r["price"])
        for uid, prices in seq.items():
            if len(prices) >= 2 and prices[0] > prices[-1]:
                out[uid] = {"first": prices[0], "current": prices[-1],
                            "cut": round(prices[0] - prices[-1], 2),
                            "pct": round((prices[0] - prices[-1]) / prices[0], 3),
                            "changes": len(prices) - 1}
        return out

    def all_listings(self) -> list:
        """Every row ever stored, newest sighting first.

        Deliberately unfiltered by date: `recent_unalerted` only ever returns
        the last week, which is a sliver of the pool and hides most of what is
        still on sale and still worth buying.
        """
        return self.conn.execute(
            "SELECT raw_json, last_seen, status FROM listings "
            "WHERE price IS NOT NULL AND (status IS NULL OR status != 'gone') "
            "ORDER BY last_seen DESC"
        ).fetchall()

    # ---------- picks (the human's shortlist) ----------

    def set_pick(self, uid: str, state: str, note: str | None = None):
        """state 'interested' / 'hidden', or anything else to clear the pick."""
        if state not in ("interested", "hidden"):
            self.conn.execute("DELETE FROM picks WHERE uid = ?", (uid,))
        else:
            self.conn.execute(
                "INSERT INTO picks (uid, state, note, updated_at) "
                "VALUES (?,?,?,datetime('now')) "
                "ON CONFLICT(uid) DO UPDATE SET state=excluded.state, "
                "note=COALESCE(excluded.note, picks.note), "
                "updated_at=excluded.updated_at",
                (uid, state, note),
            )
        self.conn.commit()

    def picks(self) -> dict:
        return {r["uid"]: r for r in self.conn.execute("SELECT * FROM picks")}

    # ---------- stats ----------

    def counts(self) -> dict:
        n_listings = self.conn.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"]
        n_alerts = self.conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]
        n_priced = self.conn.execute(
            "SELECT COUNT(*) c FROM listings WHERE primary_component IS NOT NULL"
        ).fetchone()["c"]
        n_components = self.conn.execute(
            "SELECT COUNT(DISTINCT primary_component) c FROM listings "
            "WHERE primary_component IS NOT NULL"
        ).fetchone()["c"]
        return {"listings": n_listings, "alerts": n_alerts,
                "single_items": n_priced, "components_tracked": n_components}


def median_or_none(values: list[float]) -> float | None:
    return median(values) if values else None
