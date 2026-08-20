"""Is this ad still for sale? Ask the search, never the ad page.

The board was handing out dead links, which is the fastest way to make the
whole tool worthless: two of the three best PS5s it offered had been gone for
weeks. Nothing ever checked, because nothing ever could -- `status` and
`disappeared_at` have been in the schema since day one and no code path wrote
to them.

Fetching the ad page does not work. Measured 2026-08-18: Leboncoin answers
HTTP 410 with a byte-identical 436 KB body for live and expired ads alike, so
the status code carries no information about the listing at all.

Re-running the ad's own search does work. The listing's id either comes back or
it does not, and that is the same channel that found it in the first place:

    Menen PS5, board said alive       -> absent from 50 results -> gone
    Roeselare Steam Deck, "ne part pas" -> present               -> really still up

Absence is strong but not proof: a generic query can bury a live ad past the
result window. So a miss marks the listing gone for display purposes and is
worth re-confirming, while a hit is taken as certain.
"""
from __future__ import annotations

import logging
import random
import re
import time

from .config import SearchConfig

log = logging.getLogger(__name__)

_2EM_URL = ("https://www.2ememain.be/lrp/api/search?query={q}&limit=50&offset=0"
            "&sortBy=SORT_INDEX&sortOrder=DECREASING")
_LBC_URL = "https://www.leboncoin.fr/recherche?text={q}"

# Words that identify nothing. A query built from these matches half the site
# and would "confirm" any listing as alive.
_NOISE = {
    "a", "au", "aux", "de", "du", "des", "le", "la", "les", "un", "une", "et",
    "en", "pour", "avec", "sans", "sur", "dans", "par", "tres", "bon", "bonne",
    "etat", "neuf", "neuve", "occasion", "vends", "vend", "vendre", "urgent",
    "the", "and", "with", "for", "van", "met", "een", "de", "het", "zeer",
    "goede", "staat", "nieuw", "nieuwstaat", "te", "koop", "als", "in", "of",
    "complet", "complete", "compleet", "pas", "cher", "prix", "euro", "euros",
}


def query_for(title: str, max_terms: int = 4) -> str:
    """The most identifying words of a title, in order.

    Order is kept rather than sorting by length: "steam deck oled 512" is a
    query, "512 oled deck steam" is noise to a relevance ranker.
    """
    toks = [t for t in re.split(r"[^0-9a-zà-ÿ]+", (title or "").lower()) if t]
    keep = [t for t in toks if len(t) > 1 and t not in _NOISE]
    return " ".join(keep[:max_terms])


def _ids_from(source, name: str, query: str) -> set[str] | None:
    """Ids the source returns for this query, or None when the check failed.

    None is not "gone" -- a blocked or erroring source must never be allowed to
    mark half the pool dead.
    """
    url = (_2EM_URL if name == "2ememain" else _LBC_URL).format(
        q=query.replace(" ", "%20"))
    try:
        listings = source.fetch(SearchConfig(name=f"verify:{query}", url=url,
                                             source=name, kind="feeder"))
    except Exception:
        log.warning("liveness: %s search failed for %r", name, query, exc_info=True)
        return None
    return {l.source_id for l in listings}


def verify(store, sources, uids, pause: tuple[float, float] = (1.5, 3.5)) -> dict:
    """Re-search each listing and record whether it is still on sale.

    One request per listing, so callers pass the handful they are about to act
    on, not the whole pool.

    Returns counts plus a per-uid verdict under "results", each one of "alive",
    "gone" or "skipped". Callers MUST keep "skipped" distinct from "alive": the
    first report of this run showed DataDome-blocked Leboncoin ads as confirmed
    on sale, which is the same false confidence that made the board hand out
    dead links in the first place.
    """
    stats = {"checked": 0, "alive": 0, "gone": 0, "skipped": 0}
    results: dict[str, str] = {}
    stats["results"] = results
    for i, uid in enumerate(uids):
        results[uid] = "skipped"
        row = store.conn.execute(
            "SELECT source, source_id, title FROM listings WHERE uid = ?", (uid,)
        ).fetchone()
        if row is None:
            stats["skipped"] += 1
            continue
        source = sources.get(row["source"])
        query = query_for(row["title"])
        if source is None or not query:
            stats["skipped"] += 1
            continue

        if i:
            time.sleep(random.uniform(*pause))
        ids = _ids_from(source, row["source"], query)
        if ids is None:
            stats["skipped"] += 1
            continue

        stats["checked"] += 1
        if row["source_id"] in ids:
            store.mark_alive(uid)
            stats["alive"] += 1
            results[uid] = "alive"
        else:
            store.mark_gone(uid)
            stats["gone"] += 1
            results[uid] = "gone"
    return stats
