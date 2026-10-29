"""Is this listing still for sale?

A listing that left the site is the closest thing to a sale we can observe (it
feeds the tracker's "sold" prices and the time to sell), and a dead link shown
as a deal is the fastest way to lose the person using the tool. So listings
worth knowing about are re-checked, a few per cycle.

Each source answers in its own way (`source.is_online(row)`):
- Leboncoin: never the ad page, which answers HTTP 410 with the same body for
  live and expired ads (measured 2026-08-18), but a search narrow enough that
  a live ad must come back;
- 2ememain: a search on the title's identifying words;
- shops: the product page, which says "rupture de stock".

The answer is True (online), False (gone) or None (could not tell). Only an
explicit False marks a listing gone: a blocked or failing source must never
declare half the pool dead. The first failure stops that source for the run.
"""
from __future__ import annotations

import logging
import random
import re
import time

log = logging.getLogger(__name__)

# Words that identify nothing. A query built from these matches half the site.
_NOISE = {
    "a", "au", "aux", "de", "du", "des", "le", "la", "les", "un", "une", "et",
    "en", "pour", "avec", "sans", "sur", "dans", "par", "tres", "bon", "bonne",
    "etat", "neuf", "neuve", "occasion", "vends", "vend", "vendre", "urgent",
    "the", "and", "with", "for", "van", "met", "een", "het", "zeer",
    "goede", "staat", "nieuw", "nieuwstaat", "te", "koop", "als", "in", "of",
    "complet", "complete", "compleet", "pas", "cher", "prix", "euro", "euros",
}


def query_for(title: str | None, max_terms: int = 4) -> str:
    """The most identifying words of a title, in their order ("steam deck
    oled" is a query, "oled deck steam" is noise to a relevance ranker)."""
    toks = [t for t in re.split(r"[^0-9a-zà-ÿ]+", (title or "").lower()) if t]
    return " ".join([t for t in toks if len(t) > 1 and t not in _NOISE][:max_terms])


def check(store, source, rows, pause: tuple[float, float] = (2.0, 5.0)) -> dict:
    """Re-check `rows` (listings rows of one source) and record the answers.
    Returns {"alive", "gone", "unknown", "results": {uid: verdict}}."""
    stats = {"alive": 0, "gone": 0, "unknown": 0, "results": {}}
    is_online = getattr(source, "is_online", None)
    for i, row in enumerate(rows):
        verdict = "unknown"
        if is_online is not None:
            if i:
                time.sleep(random.uniform(*pause))
            try:
                online = is_online(row)
            except Exception:
                log.warning("liveness: %s stopped after a failure", getattr(source, "name", "?"),
                            exc_info=log.isEnabledFor(logging.DEBUG))
                is_online = None
            else:
                if online is True:
                    store.mark_alive(row["uid"])
                    verdict = "alive"
                elif online is False:
                    store.mark_gone(row["uid"])
                    verdict = "gone"
                else:
                    store.mark_checked(row["uid"])
        stats[verdict] += 1
        stats["results"][row["uid"]] = verdict
    return stats


def verify(store, sources: dict, uids, pause: tuple[float, float] = (1.5, 3.5)) -> dict:
    """Re-check specific listings (the board's best offers), across sources."""
    by_source: dict[str, list] = {}
    out = {"alive": 0, "gone": 0, "unknown": 0, "results": {}}
    for uid in uids:
        row = store.get(uid)
        if row is None or row["source"] not in sources:
            out["unknown"] += 1
            out["results"][uid] = "unknown"
            continue
        by_source.setdefault(row["source"], []).append(row)
    for name, rows in by_source.items():
        stats = check(store, sources[name], rows, pause)
        for k in ("alive", "gone", "unknown"):
            out[k] += stats[k]
        out["results"].update(stats["results"])
    return out


# A shop's search feed lags its product pages: Cash Converters listed five
# Galaxy S26 with a working cart link hours after their pages died, and Cash
# Express keeps items its own page calls "rupture de stock".
_OUT_OF_STOCK = ("rupture de stock", "out of stock", "niet meer beschikbaar",
                 "n'est plus disponible", "plus disponible")
_STUB_BYTES = 800       # a deleted product page comes back as an empty stub


def page_online(resp) -> bool | None:
    """From one fetched product page: True (buyable), False (gone or out of
    stock), None (the shop did not really answer: blocked, server error)."""
    code = getattr(resp, "status_code", 200)
    if code in (404, 410):
        return False
    if code != 200:
        return None
    body = (getattr(resp, "text", "") or "").lower()
    if len(body) < _STUB_BYTES:
        return False
    return not any(w in body for w in _OUT_OF_STOCK)
