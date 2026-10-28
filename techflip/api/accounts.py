"""Account-side persistence for the app backend (same SQLite file as the
scanner, separate tables).

Accounts are anonymous and device-bound: installing the app creates a user tied
to an attested device key. No email, no password, nothing to leak. The paid
subscription is tied to that user id through RevenueCat, and "Restaurer mes
achats" on a new phone moves it to that phone's user.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..db import open_db

_BASE = """
CREATE TABLE IF NOT EXISTS users (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    platform         TEXT,
    status           TEXT NOT NULL DEFAULT 'active',     -- active | banned
    home_lat         REAL,
    home_lng         REAL,
    home_label       TEXT,
    radius_km        REAL DEFAULT 60,
    include_shipping INTEGER DEFAULT 1,
    min_profit       REAL DEFAULT 30,
    categories       TEXT DEFAULT '[]',
    notify           INTEGER DEFAULT 1,
    notify_mode      TEXT DEFAULT 'instant',              -- instant | daily
    push_token       TEXT,
    entitled_until   TEXT,                                -- ISO, NULL = never
    entitlement_product TEXT,
    entitlement_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,          -- iOS App Attest key id, or server id
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,             -- ios | android | dev
    public_key  BLOB,                      -- iOS: attested key (DER)
    counter     INTEGER DEFAULT 0,
    receipt     BLOB,
    created_at  TEXT NOT NULL,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    hash        TEXT PRIMARY KEY,          -- sha256 of the token, never the token
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id   TEXT NOT NULL,
    family      TEXT NOT NULL,             -- one login = one family
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_rt_family ON refresh_tokens(family);

CREATE TABLE IF NOT EXISTS challenges (
    value       TEXT PRIMARY KEY,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, uid)
);

CREATE TABLE IF NOT EXISTS hidden (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid     TEXT NOT NULL,
    reason  TEXT NOT NULL,                 -- not_interested | sold
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, uid)
);

CREATE TABLE IF NOT EXISTS notified (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid     TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, uid)
);

CREATE TABLE IF NOT EXISTS usage (
    user_id TEXT NOT NULL,
    day     TEXT NOT NULL,
    kind    TEXT NOT NULL,
    n       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);
"""

PREF_FIELDS = ("home_lat", "home_lng", "home_label", "radius_km", "include_shipping",
               "min_profit", "categories", "notify", "notify_mode")

# Append only; never edit a shipped step (see techflip/db.py).
MIGRATIONS = (("accounts/001_schema", _BASE),)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenReuse(Exception):
    """A refresh token was presented twice: someone copied it. The whole
    family is revoked, logging out both the thief and the victim's session."""


class Accounts:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn: sqlite3.Connection = open_db(db_path, "accounts", MIGRATIONS)

    def close(self):
        self.conn.close()

    # ---------- challenges (single use, short-lived) ----------

    def new_challenge(self, ttl_s: int = 300) -> str:
        value = secrets.token_urlsafe(32)
        self.conn.execute("DELETE FROM challenges WHERE expires_at < ?", (_iso(_now()),))
        self.conn.execute("INSERT INTO challenges (value, expires_at) VALUES (?,?)",
                          (value, _iso(_now() + timedelta(seconds=ttl_s))))
        self.conn.commit()
        return value

    def consume_challenge(self, value: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM challenges WHERE value=? AND expires_at >= ?", (value, _iso(_now())))
        self.conn.commit()
        return cur.rowcount == 1

    # ---------- users / devices ----------

    def create_user(self, platform: str, device_id: str, public_key: bytes | None = None,
                    receipt: bytes | None = None) -> str:
        uid = str(uuid.uuid4())
        now = _iso(_now())
        self.conn.execute("INSERT INTO users (id, created_at, platform) VALUES (?,?,?)",
                          (uid, now, platform))
        self.conn.execute(
            "INSERT INTO devices (id, user_id, platform, public_key, counter, receipt, "
            "created_at, last_seen) VALUES (?,?,?,?,?,?,?,?)",
            (device_id, uid, platform, public_key, 0, receipt, now, now))
        self.conn.commit()
        return uid

    def device_exists(self, device_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone() is not None

    def device(self, device_id: str):
        return self.conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()

    def bump_device(self, device_id: str, counter: int | None = None):
        if counter is None:
            self.conn.execute("UPDATE devices SET last_seen=? WHERE id=?", (_iso(_now()), device_id))
        else:
            self.conn.execute("UPDATE devices SET last_seen=?, counter=? WHERE id=?",
                              (_iso(_now()), counter, device_id))
        self.conn.commit()

    def user(self, user_id: str):
        return self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def update_prefs(self, user_id: str, prefs: dict):
        cols, vals = [], []
        for k in PREF_FIELDS:
            if k in prefs:
                v = prefs[k]
                if k == "categories":
                    v = json.dumps(sorted(set(v)))
                elif k in ("include_shipping", "notify"):
                    v = int(bool(v))
                cols.append(f"{k}=?")
                vals.append(v)
        if cols:
            self.conn.execute(f"UPDATE users SET {', '.join(cols)} WHERE id=?", (*vals, user_id))
            self.conn.commit()

    def set_push_token(self, user_id: str, token: str | None):
        if token:
            # One device token belongs to one user (reinstall = new user).
            self.conn.execute("UPDATE users SET push_token=NULL WHERE push_token=? AND id<>?",
                              (token, user_id))
        self.conn.execute("UPDATE users SET push_token=? WHERE id=?", (token, user_id))
        self.conn.commit()

    def clear_push_token(self, token: str):
        self.conn.execute("UPDATE users SET push_token=NULL WHERE push_token=?", (token,))
        self.conn.commit()

    def set_entitlement(self, user_id: str, until: datetime | None, product: str | None):
        self.conn.execute(
            "UPDATE users SET entitled_until=?, entitlement_product=?, entitlement_checked_at=? "
            "WHERE id=?",
            (_iso(until) if until else None, product, _iso(_now()), user_id))
        self.conn.commit()

    def delete_user(self, user_id: str):
        self.conn.execute("DELETE FROM refresh_tokens WHERE user_id=?", (user_id,))
        self.conn.execute("DELETE FROM devices WHERE user_id=?", (user_id,))
        self.conn.execute("DELETE FROM usage WHERE user_id=?", (user_id,))
        self.conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        self.conn.commit()

    def existing_user_ids(self, ids) -> list[str]:
        ids = [i for i in dict.fromkeys(ids) if i]
        if not ids:
            return []
        rows = self.conn.execute(
            f"SELECT id FROM users WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return [r["id"] for r in rows]

    def push_audience(self) -> list[sqlite3.Row]:
        """Subscribers who want pushes and have somewhere to receive them."""
        return self.conn.execute(
            "SELECT * FROM users WHERE status='active' AND notify=1 AND push_token IS NOT NULL "
            "AND home_lat IS NOT NULL AND entitled_until > ?", (_iso(_now()),)).fetchall()

    def active_origins(self) -> list[tuple[float, float]]:
        rows = self.conn.execute(
            "SELECT home_lat, home_lng FROM users WHERE status='active' AND home_lat IS NOT NULL "
            "AND entitled_until > ?", (_iso(_now()),)).fetchall()
        return [(r["home_lat"], r["home_lng"]) for r in rows]

    # ---------- refresh tokens (rotating, reuse-detecting) ----------

    def issue_refresh(self, user_id: str, device_id: str, ttl_s: int,
                      family: str | None = None) -> str:
        token = secrets.token_urlsafe(48)
        self.conn.execute(
            "INSERT INTO refresh_tokens (hash, user_id, device_id, family, expires_at) "
            "VALUES (?,?,?,?,?)",
            (hash_token(token), user_id, device_id, family or secrets.token_hex(16),
             _iso(_now() + timedelta(seconds=ttl_s))))
        self.conn.commit()
        return token

    def peek_refresh(self, token: str):
        """Look a refresh token up without consuming it, so a request whose
        device proof fails does not burn the legitimate client's token."""
        return self.conn.execute("SELECT * FROM refresh_tokens WHERE hash=?",
                                 (hash_token(token),)).fetchone()

    def use_refresh(self, token: str):
        """Mark a refresh token used and return its row, or None if unknown or
        expired. Raises TokenReuse if it was already used."""
        row = self.conn.execute("SELECT * FROM refresh_tokens WHERE hash=?",
                                (hash_token(token),)).fetchone()
        if row is None:
            return None
        if row["used_at"] is not None:
            self.conn.execute("DELETE FROM refresh_tokens WHERE family=?", (row["family"],))
            self.conn.commit()
            raise TokenReuse(row["family"])
        if row["expires_at"] < _iso(_now()):
            return None
        self.conn.execute("UPDATE refresh_tokens SET used_at=? WHERE hash=?",
                          (_iso(_now()), row["hash"]))
        self.conn.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (_iso(_now()),))
        self.conn.commit()
        return row

    def revoke_user_tokens(self, user_id: str):
        self.conn.execute("DELETE FROM refresh_tokens WHERE user_id=?", (user_id,))
        self.conn.commit()

    # ---------- saved / hidden / notified ----------

    def save(self, user_id: str, uid: str):
        self.conn.execute("INSERT OR IGNORE INTO saved (user_id, uid, created_at) VALUES (?,?,?)",
                          (user_id, uid, _iso(_now())))
        self.conn.commit()

    def unsave(self, user_id: str, uid: str):
        self.conn.execute("DELETE FROM saved WHERE user_id=? AND uid=?", (user_id, uid))
        self.conn.commit()

    def saved_uids(self, user_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT uid FROM saved WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [r["uid"] for r in rows]

    def hide(self, user_id: str, uid: str, reason: str) -> int:
        """Returns how many distinct users reported this listing as sold."""
        self.conn.execute(
            "INSERT OR REPLACE INTO hidden (user_id, uid, reason, created_at) VALUES (?,?,?,?)",
            (user_id, uid, reason, _iso(_now())))
        self.conn.commit()
        return self.conn.execute(
            "SELECT COUNT(*) c FROM hidden WHERE uid=? AND reason='sold'", (uid,)).fetchone()["c"]

    def hidden_uids(self, user_id: str) -> set[str]:
        rows = self.conn.execute("SELECT uid FROM hidden WHERE user_id=?", (user_id,)).fetchall()
        return {r["uid"] for r in rows}

    def notified_uids(self, user_id: str, uids) -> set[str]:
        uids = list(uids)
        if not uids:
            return set()
        rows = self.conn.execute(
            f"SELECT uid FROM notified WHERE user_id=? AND uid IN ({','.join('?' * len(uids))})",
            (user_id, *uids)).fetchall()
        return {r["uid"] for r in rows}

    def mark_notified(self, user_id: str, uids):
        now = _iso(_now())
        self.conn.executemany(
            "INSERT OR IGNORE INTO notified (user_id, uid, sent_at) VALUES (?,?,?)",
            [(user_id, u, now) for u in uids])
        self.conn.commit()

    # ---------- retention ----------

    def prune(self, keep_days: int = 30) -> None:
        """Drop bookkeeping that only matters for a few days: push and usage
        logs, expired challenges and refresh tokens."""
        now = _now()
        cutoff = _iso(now - timedelta(days=keep_days))
        self.conn.execute("DELETE FROM notified WHERE sent_at < ?", (cutoff,))
        self.conn.execute("DELETE FROM usage WHERE day < ?", (cutoff[:10],))
        self.conn.execute("DELETE FROM challenges WHERE expires_at < ?", (_iso(now),))
        self.conn.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (_iso(now),))
        self.conn.commit()

    # ---------- usage counters (abuse ceilings) ----------

    def usage_today(self, user_id: str, kind: str) -> int:
        row = self.conn.execute("SELECT n FROM usage WHERE user_id=? AND day=? AND kind=?",
                                (user_id, _now().strftime("%Y-%m-%d"), kind)).fetchone()
        return row["n"] if row else 0

    def bump_usage(self, user_id: str, kind: str) -> int:
        day = _now().strftime("%Y-%m-%d")
        self.conn.execute(
            "INSERT INTO usage (user_id, day, kind, n) VALUES (?,?,?,1) "
            "ON CONFLICT(user_id, day, kind) DO UPDATE SET n = n + 1", (user_id, day, kind))
        self.conn.commit()
        return self.conn.execute("SELECT n FROM usage WHERE user_id=? AND day=? AND kind=?",
                                 (user_id, day, kind)).fetchone()["n"]
