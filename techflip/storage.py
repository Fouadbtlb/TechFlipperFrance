"""SQLite persistence for the scanner side.

Every listing ever seen is kept: it is the price dataset the tracker learns from.
The scanner (writer) and the API (readers) share the file, so it runs in WAL
mode with a busy timeout.

Tables:
- listings      : everything scraped, plus its location-independent appraisal
- price_history : one row per observed price change (feeds "prix en baisse")
- alerts        : listings already sent to the owner's Telegram (never twice)
- price_feedback: subscribers' verdicts on our estimates and their real
                  resale prices, one row per user and listing

A listing that leaves the site ("partie") is the closest thing to a sale we can
observe: its last price feeds the tracker ahead of asking prices, and how long
it stayed up gives the time to sell.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import tuning
from .db import connect, open_db
from .domain import Listing

__all__ = ["Store", "connect", "title_key"]

# The whole schema. Future changes are appended to MIGRATIONS as new steps
# (see db.py); this first step is the fresh-install schema.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid            TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    search_name    TEXT,
    url            TEXT,
    title          TEXT,
    title_key      TEXT,          -- normalized title, for repost detection
    price          REAL,
    last_price     REAL,          -- previous price when it changed (price drops)
    brand          TEXT,
    model          TEXT,
    condition      TEXT,
    city           TEXT,
    zipcode        TEXT,
    department     TEXT,
    country        TEXT,
    lat            REAL,
    lng            REAL,
    owner_type     TEXT,
    has_phone      INTEGER,
    seller_id      TEXT,
    published_at   TEXT,
    fetched_at     TEXT,
    raw_json       TEXT,          -- the normalized Listing, for re-valuation and detail
    first_seen     TEXT,
    last_seen      TEXT,
    status         TEXT DEFAULT 'active',   -- active | gone
    last_checked   TEXT,          -- last time we confirmed it was still online
    disappeared_at TEXT,
    days_on_market REAL,
    repost_of      TEXT,          -- uid of the first listing of this item
    reposts        INTEGER,       -- how many times it was put back online
    primary_component TEXT,       -- set for single-item listings: they teach the tracker
    is_single      INTEGER,
    category       TEXT,
    true_value     REAL,
    margin         REAL,          -- true_value - price, before anyone's logistics
    confidence     REAL,
    appraisal      TEXT,          -- JSON: breakdown, risk, shipping, seller, floor...
    appraised_at   TEXT,
    llm_verdict    TEXT,          -- cached vision verdict ...
    llm_price      REAL,          -- ... valid while the price is unchanged
    net_profit     REAL,          -- the owner's (Telegram) view, for `cli top`
    zone           TEXT,
    distance_km    REAL
);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings(fetched_at);
CREATE INDEX IF NOT EXISTS idx_listings_primary ON listings(primary_component);
CREATE INDEX IF NOT EXISTS idx_listings_margin ON listings(margin);
CREATE INDEX IF NOT EXISTS idx_listings_titlekey ON listings(title_key);

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

CREATE TABLE IF NOT EXISTS price_feedback (
    user_id      TEXT NOT NULL,
    uid          TEXT NOT NULL,
    verdict      TEXT,            -- low | fair | high: our estimate is too low / right / too high
    resale_price REAL,            -- what they actually resold it for, if they did
    created_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_feedback_uid ON price_feedback(uid);

CREATE TABLE IF NOT EXISTS meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MIGRATIONS = (("store/001_schema", _SCHEMA),)


def title_key(title: str | None) -> str:
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", t))

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_between(start: str | None, end: str) -> float | None:
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 86400, 2)
    except (TypeError, ValueError):
        return None


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = open_db(db_path, "store", MIGRATIONS)

    def close(self) -> None:
        self.conn.close()

    # ---------- meta (scanner heartbeat, small state) ----------

    def set_meta(self, key: str, value: dict) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), _now()))
        self.conn.commit()

    def get_meta(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT value, updated_at FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        return {**json.loads(row["value"]), "updated_at": row["updated_at"]}

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
        if is_new:
            self._link_repost(l)
        if is_new or (l.price is not None and l.price != old_price):
            self.conn.execute(
                "INSERT INTO price_history (uid, price, seen_at) VALUES (?,?,?)",
                (l.uid, l.price, l.fetched_at),
            )
        self.conn.commit()
        return is_new

    def _link_repost(self, l: Listing):
        """Same seller, same title (or, without seller ids, same title, city and
        a close price) within 60 days: the item was put back online. Unsold
        reposts are negotiation leverage, and duplicates are hidden."""
        key = title_key(l.title)
        if len(key) < 6:
            self.conn.execute("UPDATE listings SET title_key=? WHERE uid=?", (key, l.uid))
            return
        since = datetime.fromisoformat(l.fetched_at.replace("Z", "+00:00"))
        since = (since - tuning.REPOST_WINDOW).isoformat()
        if l.seller_id:
            prev = self.conn.execute(
                "SELECT uid, repost_of, reposts FROM listings WHERE title_key=? AND source=? "
                "AND seller_id=? AND uid<>? AND first_seen>=? ORDER BY first_seen LIMIT 1",
                (key, l.source, l.seller_id, l.uid, since)).fetchone()
        elif l.price:
            prev = self.conn.execute(
                "SELECT uid, repost_of, reposts FROM listings WHERE title_key=? AND source=? "
                "AND seller_id IS NULL AND city IS ? AND price BETWEEN ? AND ? AND uid<>? "
                "AND first_seen>=? ORDER BY first_seen LIMIT 1",
                (key, l.source, l.city, 0.85 * l.price, 1.15 * l.price, l.uid, since)).fetchone()
        else:
            prev = None
        if prev is None:
            self.conn.execute("UPDATE listings SET title_key=? WHERE uid=?", (key, l.uid))
            return
        root = prev["repost_of"] or prev["uid"]
        n = self.conn.execute("SELECT COUNT(*) c FROM listings WHERE repost_of=?", (root,)).fetchone()["c"] + 1
        self.conn.execute("UPDATE listings SET title_key=?, repost_of=?, reposts=? WHERE uid=?",
                          (key, root, n, l.uid))

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

    def mark_gone(self, uid: str, at: str | None = None):
        """The listing left the site (or two subscribers reported it sold)."""
        at = at or _now()
        row = self.conn.execute("SELECT first_seen, status FROM listings WHERE uid=?", (uid,)).fetchone()
        if row is None or row["status"] == "gone":
            return
        days = _days_between(row["first_seen"], at)
        self.conn.execute(
            "UPDATE listings SET status='gone', disappeared_at=?, days_on_market=?, last_checked=? "
            "WHERE uid=?", (at, days, at, uid))
        self.conn.commit()

    def mark_checked(self, uid: str):
        self.conn.execute("UPDATE listings SET last_checked=? WHERE uid=?", (_now(), uid))
        self.conn.commit()

    def due_for_check(self, limit: int, source: str) -> list[sqlite3.Row]:
        """Which active listings to re-check, most useful first: deals people
        can see (every 3 h, so dead deals leave the feed), then single items
        that teach the tracker (every 2 days)."""
        now = datetime.now(timezone.utc)
        deals_before = (now - tuning.RECHECK_DEALS_EVERY).isoformat()
        comps_before = (now - tuning.RECHECK_COMPONENTS_EVERY).isoformat()
        horizon = (now - tuning.RECHECK_HORIZON).isoformat()
        return self.conn.execute(
            """SELECT uid, source_id, url FROM listings
               WHERE status='active' AND source=? AND first_seen>=?
                 AND ((margin > 0 AND appraisal IS NOT NULL AND IFNULL(last_checked, first_seen) < ?)
                      OR (primary_component IS NOT NULL AND IFNULL(last_checked, first_seen) < ?))
               ORDER BY (margin > 0) DESC, IFNULL(last_checked, first_seen)
               LIMIT ?""",
            (source, horizon, deals_before, comps_before, limit)).fetchall()

    def sold_prices(self, key: str, since_iso: str, exclude_uid: str | None = None) -> list[float]:
        """Closest thing to sale prices: last price of single items that left
        the site, plus resale prices subscribers reported for that item."""
        rows = self.conn.execute(
            """SELECT price AS p FROM listings
               WHERE primary_component=? AND status='gone' AND price IS NOT NULL
                 AND disappeared_at>=? AND uid IS NOT ?
               UNION ALL
               SELECT f.resale_price AS p FROM price_feedback f JOIN listings l ON l.uid=f.uid
               WHERE l.primary_component=? AND f.resale_price IS NOT NULL AND f.created_at>=?""",
            (key, since_iso, exclude_uid, key, since_iso)).fetchall()
        return [r["p"] for r in rows]

    def days_to_sell(self, key: str, since_iso: str) -> list[float]:
        rows = self.conn.execute(
            "SELECT days_on_market d FROM listings WHERE primary_component=? AND status='gone' "
            "AND days_on_market IS NOT NULL AND disappeared_at>=?", (key, since_iso)).fetchall()
        return [r["d"] for r in rows]

    def feedback_factor(self, key: str, since_iso: str) -> float:
        """Subscribers' verdicts on single-item estimates for this component,
        turned into a bounded correction: 'too high' pulls the value down."""
        rows = self.conn.execute(
            """SELECT f.verdict v, COUNT(DISTINCT f.user_id) n FROM price_feedback f
               JOIN listings l ON l.uid=f.uid
               WHERE l.primary_component=? AND f.verdict IS NOT NULL AND f.created_at>=?
               GROUP BY f.verdict""", (key, since_iso)).fetchall()
        votes = {r["v"]: r["n"] for r in rows}
        total = sum(votes.values())
        if total < tuning.FEEDBACK_MIN_VOTES:
            return 1.0
        lean = (votes.get("low", 0) - votes.get("high", 0)) / total
        return round(1.0 + tuning.FEEDBACK_MAX_SHIFT * lean, 4)

    def add_feedback(self, user_id: str, uid: str, verdict: str | None, resale_price: float | None):
        self.conn.execute(
            """INSERT INTO price_feedback (user_id, uid, verdict, resale_price, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, uid) DO UPDATE SET
                 verdict=COALESCE(excluded.verdict, verdict),
                 resale_price=COALESCE(excluded.resale_price, resale_price),
                 created_at=excluded.created_at""",
            (user_id, uid, verdict, resale_price, _now()))
        self.conn.commit()

    def feedback_summary(self, uid: str, user_id: str | None = None) -> dict:
        rows = self.conn.execute(
            "SELECT verdict, COUNT(*) n FROM price_feedback WHERE uid=? AND verdict IS NOT NULL "
            "GROUP BY verdict", (uid,)).fetchall()
        out = {"low": 0, "fair": 0, "high": 0, "mine": None, "my_resale": None}
        for r in rows:
            out[r["verdict"]] = r["n"]
        if user_id:
            me = self.conn.execute("SELECT verdict, resale_price FROM price_feedback WHERE uid=? AND user_id=?",
                                   (uid, user_id)).fetchone()
            if me:
                out["mine"], out["my_resale"] = me["verdict"], me["resale_price"]
        return out

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

    # ---------- retention ----------

    def prune(self, keep_days: int = 90) -> dict:
        """Keep the database small: what is older than the tracker's window is
        never read again. Gone listings past the window, and listings nobody
        appraised or learned from that have not been seen for that long, are
        deleted with their price history. Feedback stays (it is sale data)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        conn = self.conn
        doomed = """SELECT uid FROM listings WHERE
                      (status='gone' AND disappeared_at < :c)
                   OR (last_seen < :c AND primary_component IS NULL AND (margin IS NULL OR margin <= 0))"""
        history = conn.execute(f"DELETE FROM price_history WHERE uid IN ({doomed})", {"c": cutoff}).rowcount
        alerts = conn.execute(f"DELETE FROM alerts WHERE uid IN ({doomed})", {"c": cutoff}).rowcount
        listings = conn.execute(f"DELETE FROM listings WHERE uid IN ({doomed})", {"c": cutoff}).rowcount
        # Cached vision verdicts and the full listing JSON are only needed while
        # a listing is online.
        conn.execute("UPDATE listings SET llm_verdict=NULL, raw_json=NULL "
                     "WHERE status='gone' AND raw_json IS NOT NULL AND disappeared_at < :c",
                     {"c": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()})
        conn.commit()
        conn.execute("PRAGMA incremental_vacuum")
        return {"listings": listings, "price_history": history, "alerts": alerts}

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
