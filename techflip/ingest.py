"""Fill the pool from a searches file. Ingest only.

The scanner service polls a handful of fixed searches and alerts on what is
new. The shopping board reads the whole stored pool instead, so it is only as
good as how recently that pool was refreshed -- and with the service off, it
goes stale in days.

This is the refresh, and nothing else. It upserts listings and records the
component each one was recognized as, so the price tracker can learn from them.
It does not alert, does not mark anything gone, and never writes `alerted_at`:
a diagnostic that stubbed the notifier once destroyed fifteen real deals by
marking them alerted without sending them, and that must not be repeatable from
here.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from .config import SearchConfig
from .pricing.catalog import Catalog
from .hunt import teaching_key
from .storage import Store

log = logging.getLogger(__name__)

# Rows a full page holds, per source. A short page means the last one.
PER_PAGE = {"cashconverters": 48, "cashexpress": 100, "2ememain": 30,
            "leboncoin": 35}


def ingest(store: Store, searches, sources: dict, *, catalog: Catalog | None = None,
           max_pages: int = 4, per_page: int | None = None,
           sleep: float = 0.35) -> dict:
    stats = {"kept": 0, "new": 0, "errors": 0, "searches": 0}
    for s in searches:
        src = sources.get(s.source)
        if src is None:
            stats["errors"] += 1
            continue
        stats["searches"] += 1
        full = per_page or PER_PAGE.get(s.source, 30)
        for page in range(1, max_pages + 1):
            try:
                hits = src.fetch(s, page=page)
            except Exception as e:
                stats["errors"] += 1
                log.warning("ingest: %s p%s: %s: %s", s.name, page,
                            type(e).__name__, str(e)[:120])
                break
            for l in hits:
                if not _in_band(l, s):
                    continue
                stats["kept"] += 1
                if _retry(store.upsert_listing, l):
                    stats["new"] += 1
                if catalog is not None:
                    pk = teaching_key(l, catalog)
                    _retry(store.set_primary_component, l.uid, pk, bool(pk))
            if len(hits) < full:
                break
            if sleep:
                time.sleep(sleep)
    return stats


def _in_band(l, s: SearchConfig) -> bool:
    if l.price is None or l.price < s.min_price:
        return False
    return not (s.max_price and l.price > s.max_price)


def _retry(fn, *a):
    """Several ingests share one SQLite file and a writer can hold the lock
    past busy_timeout. Back off rather than lose the rest of the run."""
    for i in range(12):
        try:
            return fn(*a)
        except sqlite3.OperationalError as e:
            if "locked" not in str(e):
                raise
            time.sleep(0.5 * (i + 1))
    return fn(*a)
