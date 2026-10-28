"""SQLite plumbing shared by the scanner store and the account store.

Schema changes are named, ordered migrations recorded in `schema_migrations`.
To change the schema, append a step to the owning module's MIGRATIONS list
(for a new column: `lambda c: add_column(c, "listings", "x", "TEXT")`); never
edit a step that has already run somewhere.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

Step = str | Callable[[sqlite3.Connection], None]
Migration = tuple[str, Step]

_lock = threading.Lock()
_ready: set[tuple[str, str]] = set()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """One connection per unit of work; WAL lets the scanner write while the
    API reads."""
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> list[str]:
    """Apply the steps not yet recorded, in order. Returns the names applied."""
    # Freed pages are reclaimed by Store.prune() (PRAGMA incremental_vacuum);
    # this only takes effect on a fresh database, before the first table.
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                 "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for name, step in migrations:
        if name in done:
            continue
        if callable(step):
            step(conn)
        else:
            conn.executescript(step)
        conn.execute("INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                     (name, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        applied.append(name)
    return applied


def open_db(db_path: str | Path, owner: str, migrations: Sequence[Migration]) -> sqlite3.Connection:
    """Connect, migrating at most once per process and owner."""
    conn = connect(db_path)
    key = (str(db_path), owner)
    if key not in _ready:
        with _lock:
            if key not in _ready:
                migrate(conn, migrations)
                _ready.add(key)
    return conn
