"""SQLite persistence for the scanner side.

Every listing ever seen is kept: it is the price dataset the tracker learns from.
The scanner (writer) and the API (readers) share the file, so it runs in WAL
mode with a busy timeout.

Tables:
- listings      : everything scraped, plus its location-independent appraisal
- price_history : one row per observed price change (feeds "prix en baisse")
- alerts        : listings already sent to the owner's Telegram (never twice)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

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
    published_at   TEXT,
    fetched_at     TEXT,
    raw_json       TEXT,
    first_seen     TEXT,
    last_seen      TEXT,
    status         TEXT DEFAULT 'active',
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

# Columns added after the first release; applied in place on old databases.
_LISTING_MIGRATIONS = (
    ("country", "TEXT"), ("primary_component", "TEXT"), ("is_single", "INTEGER"),
    ("zone", "TEXT"), ("confidence", "REAL"), ("distance_km", "REAL"),
    ("lat", "REAL"), ("lng", "REAL"),
    ("category", "TEXT"),
    ("margin", "REAL"),            # true_value - price, before anyone's logistics
    ("appraisal", "TEXT"),         # JSON: breakdown, risk, flags, shipping, seller
    ("appraised_at", "TEXT"),
    ("llm_verdict", "TEXT"),       # cached vision-LLM verdict ...
    ("llm_price", "REAL"),         # ... valid while the price is unchanged
)

_init_lock = threading.Lock()
_initialized: set[str] = set()


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = connect(db_path)
        with _init_lock:
            if self.db_path not in _initialized:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.executescript(_SCHEMA)
                self._migrate()
                _initialized.add(self.db_path)

    def _migrate(self):
        acols = {r["name"] for r in self.conn.execute("PRAGMA table_info(alerts)")}
        if "tier" not in acols:
            self.conn.execute("ALTER TABLE alerts ADD COLUMN tier TEXT DEFAULT 'confirmed'")
        lcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        for col, typ in _LISTING_MIGRATIONS:
            if col not in lcols:
                self.conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_margin ON listings(margin)")
        self.conn.commit()

    # ---------- listings ----------

    def upsert_listing(self, l: Listing) -> bool:
        """Insert or refresh a listing. Returns True if it's new.

        A price change is recorded in price_history and the previous price kept
        in last_price, so a drop can be shown to the user."""
        row = self.conn.execute("SELECT price FROM listings WHERE uid = ?", (l.uid,)).fetchone()
        is_new = row is None
        old_price = None if is_new else row["price"]
        raw = json.dumps(l.to_dict(), ensure_ascii=False)

        if is_new:
            self.conn.execute(
                """
                INSERT INTO listings (
                    uid, source, source_id, search_name, url, title, price,
                    brand, model, condition,
                    city, zipcode, department, country, owner_type, has_phone, seller_id,
                    published_at, fetched_at, raw_json, first_seen, last_seen, status, lat, lng
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    l.uid, l.source, l.source_id, l.search_name, l.url, l.title, l.price,
                    l.brand, l.model, l.condition,
                    l.city, l.zipcode, l.department, l.country, l.owner_type,
                    int(l.has_phone), l.seller_id,
                    l.published_at, l.fetched_at, raw, l.fetched_at, l.fetched_at, "active",
                    l.lat, l.lng,
                ),
            )
        else:
            changed = l.price is not None and old_price is not None and l.price != old_price
            self.conn.execute(
                """UPDATE listings SET price=?, url=?, title=?, fetched_at=?, raw_json=?,
                       last_seen=?, status='active',
                       last_price = CASE WHEN ? THEN ? ELSE last_price END
                   WHERE uid=?""",
                (l.price, l.url, l.title, l.fetched_at, raw, l.fetched_at,
                 int(changed), old_price, l.uid),
            )
        if is_new or (l.price is not None and l.price != old_price):
            self.conn.execute(
                "INSERT INTO price_history (uid, price, seen_at) VALUES (?,?,?)",
                (l.uid, l.price, l.fetched_at),
            )
        self.conn.commit()
        return is_new

    def set_position(self, uid: str, lat: float | None, lng: float | None):
        self.conn.execute("UPDATE listings SET lat=?, lng=? WHERE uid=?", (lat, lng, uid))
        self.conn.commit()

    def set_primary_component(self, uid: str, primary: str | None, is_single: bool):
        self.conn.execute(
            "UPDATE listings SET primary_component=?, is_single=? WHERE uid=?",
            (primary, int(is_single), uid),
        )
        self.conn.commit()

    def save_appraisal(self, uid: str, *, true_value: float, price: float, confidence: float,
                       category: str | None, appraisal: dict):
        """Location-independent valuation. Who can profit from it (distance,
        logistics, personal bar) is decided per viewer at read time."""
        self.conn.execute(
            "UPDATE listings SET true_value=?, margin=?, confidence=?, category=?, "
            "appraisal=?, appraised_at=? WHERE uid=?",
            (true_value, round(true_value - price, 2), confidence, category,
             json.dumps(appraisal, ensure_ascii=False), _now(), uid),
        )
        self.conn.commit()

    def clear_appraisal(self, uid: str):
        self.conn.execute(
            "UPDATE listings SET margin=NULL, appraisal=NULL, appraised_at=? WHERE uid=?",
            (_now(), uid),
        )
        self.conn.commit()

    def update_owner_view(self, uid: str, net_profit: float | None, zone: str,
                          distance_km: float | None):
        """The owner's (Telegram) perspective, kept for `cli top`."""
        self.conn.execute(
            "UPDATE listings SET net_profit=?, zone=?, distance_km=? WHERE uid=?",
            (net_profit, zone, distance_km, uid),
        )
        self.conn.commit()

    def cached_verdict(self, uid: str, price: float | None) -> dict | None:
        row = self.conn.execute(
            "SELECT llm_verdict, llm_price FROM listings WHERE uid=?", (uid,)
        ).fetchone()
        if not row or not row["llm_verdict"] or row["llm_price"] != price:
            return None
        return json.loads(row["llm_verdict"])

    def cache_verdict(self, uid: str, price: float | None, verdict: dict):
        self.conn.execute(
            "UPDATE listings SET llm_verdict=?, llm_price=? WHERE uid=?",
            (json.dumps(verdict, ensure_ascii=False), price, uid),
        )
        self.conn.commit()

    def mark_gone(self, uid: str):
        self.conn.execute("UPDATE listings SET status='gone' WHERE uid=?", (uid,))
        self.conn.commit()

    def component_prices(self, key: str, since_iso: str,
                         exclude_uid: str | None = None) -> list[float]:
        """Prices of single-item listings for one component, in the recency
        window. This is what the price tracker learns from. The listing being
        appraised is excluded, or it would vouch for its own price."""
        rows = self.conn.execute(
            "SELECT price FROM listings WHERE primary_component=? AND price IS NOT NULL "
            "AND fetched_at >= ? AND uid IS NOT ?",
            (key, since_iso, exclude_uid),
        ).fetchall()
        return [r["price"] for r in rows]

    # ---------- deals (read side) ----------

    def candidates(self, since_iso: str, min_margin: float = 0.0, uids=None) -> list[sqlite3.Row]:
        """Active, appraised listings with a positive margin before logistics.
        Per-viewer filtering happens in viewer.judge()."""
        sql = ("SELECT * FROM listings WHERE status='active' AND appraisal IS NOT NULL "
               "AND margin >= ? AND fetched_at >= ?")
        params: list = [min_margin, since_iso]
        if uids is not None:
            uids = list(uids)
            if not uids:
                return []
            sql += f" AND uid IN ({','.join('?' * len(uids))})"
            params += uids
        return self.conn.execute(sql, params).fetchall()

    def get(self, uid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM listings WHERE uid=?", (uid,)).fetchone()

    def price_points(self, uid: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT price, seen_at FROM price_history WHERE uid=? ORDER BY id", (uid,)
        ).fetchall()

    # ---------- owner alerts ----------

    def already_alerted(self, uid: str) -> bool:
        return self.alert_tier(uid) is not None

    def alert_tier(self, uid: str) -> str | None:
        row = self.conn.execute("SELECT tier FROM alerts WHERE uid = ?", (uid,)).fetchone()
        return (row["tier"] or "confirmed") if row else None

    def mark_alerted(self, uid: str, true_value: float | None = None,
                     net_profit: float | None = None, tier: str = "confirmed"):
        self.conn.execute(
            "INSERT OR REPLACE INTO alerts (uid, true_value, net_profit, tier) VALUES (?,?,?,?)",
            (uid, true_value, net_profit, tier),
        )
        self.conn.commit()

    def recent_unalerted(self, since_iso: str) -> list:
        """Recent active listings never sent to the owner: re-scored each cycle
        as the tracker matures. Cheap: the LLM verdict is cached per price."""
        return self.conn.execute(
            """SELECT l.raw_json, l.search_name FROM listings l
               LEFT JOIN alerts a ON a.uid = l.uid
               WHERE a.uid IS NULL AND l.status='active' AND l.published_at >= ?""",
            (since_iso,),
        ).fetchall()

    # ---------- stats ----------

    def counts(self) -> dict:
        one = lambda sql: self.conn.execute(sql).fetchone()["c"]  # noqa: E731
        return {
            "listings": one("SELECT COUNT(*) c FROM listings"),
            "alerts": one("SELECT COUNT(*) c FROM alerts"),
            "single_items": one("SELECT COUNT(*) c FROM listings WHERE primary_component IS NOT NULL"),
            "components_tracked": one("SELECT COUNT(DISTINCT primary_component) c FROM listings "
                                      "WHERE primary_component IS NOT NULL"),
            "deals": one("SELECT COUNT(*) c FROM listings WHERE status='active' AND margin > 0"),
        }
