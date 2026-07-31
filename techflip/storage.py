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
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(str(db_path))
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
                last_seen = excluded.last_seen,
                last_price = excluded.price,
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

    def component_prices(self, key: str, since_iso: str) -> list[float]:
        """Prices of single-item listings for one component, in the recency
        window. This is what the price tracker learns from."""
        rows = self.conn.execute(
            "SELECT price FROM listings WHERE primary_component=? AND price IS NOT NULL "
            "AND fetched_at >= ?",
            (key, since_iso),
        ).fetchall()
        return [r["price"] for r in rows]

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
