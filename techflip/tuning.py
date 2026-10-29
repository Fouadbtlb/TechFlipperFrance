"""Business knobs that are not per-deployment settings.

Deployment settings (tokens, thresholds you tune per city, API keys) live in
config.py / .env. This file holds the product rules: how cautious we are, how
often we push, how much the crowd may move a price. Change them here and the
whole backend follows; each one is covered by a test.
"""
from __future__ import annotations

from datetime import time, timedelta

# ---- valuation ------------------------------------------------------------

# Subscribers' verdicts shift an estimate only once this many different
# people voted on that component, and never by more than this fraction.
FEEDBACK_MIN_VOTES = 5
FEEDBACK_MAX_SHIFT = 0.10
# A reported resale price outside [low, high] x our value is rejected as a typo.
RESALE_PLAUSIBLE = (0.3, 3.0)

# Below this confidence (or with a high risk), a deal goes to "À vérifier".
RELIABLE_CONFIDENCE = 0.4

# ---- listing lifecycle ------------------------------------------------------

# Deals people can see are re-checked often so dead ones leave the feed;
# single items that teach the tracker, less often.
RECHECK_DEALS_EVERY = timedelta(hours=3)
RECHECK_COMPONENTS_EVERY = timedelta(days=2)
RECHECK_HORIZON = timedelta(days=60)
# Same seller + same title within this window = the item was put back online.
REPOST_WINDOW = timedelta(days=60)
# Leboncoin re-check: a search on the title words, this price band around the
# listing's price (sellers cut, sometimes raise) and this radius around it.
RECHECK_PRICE_BAND = (0.6, 1.1)
RECHECK_RADIUS_M = 10_000

# ---- shopping board ----------------------------------------------------------

BOARD_BAIT_RATIO = 0.45          # under this share of market value: bait, ranked last
BOARD_STALE_DAYS = 10            # not seen for this long: probably gone
BOARD_SITTING_DAYS = 10          # still online this long after first seen: did not sell
TOWER_REALIZATION = 0.85         # what a whole tower fetches against the towers' median ask
TOWER_MAX_SPREAD = 0.4           # comparable towers spread wider than this: no opinion

# ---- negotiation -------------------------------------------------------------

OPENING_DISCOUNT = 0.12          # opening offer below the asking price
OPENING_DISCOUNT_REPOSTED = 0.18 # more room when the item did not sell before
OPENING_FLOOR = 0.75             # never open below this share of the ask

# ---- notifications -----------------------------------------------------------

QUIET_START = time(22, 0)        # Europe/Paris
QUIET_END = time(8, 0)
MAX_PUSHES_PER_DAY = 8
NOTIFY_WINDOW = timedelta(hours=12)   # older deals are no longer news
DIGEST_HOUR = 18                 # evening summary for notify_mode="daily"
DIGEST_WINDOW = timedelta(hours=24)

# ---- payloads ----------------------------------------------------------------

MAP_MAX_PINS = 250

# ---- trusted sellers ---------------------------------------------------------

# Second-hand chains: the item sits on a shelf, tested and under warranty, and
# you collect it or it ships from the shop. The checks built for private ads
# (AI photo check, "too cheap from far away = scam") do not apply to them.
SHOP_SOURCES = frozenset({"cashconverters", "cashexpress"})

# ---- operations --------------------------------------------------------------

# /v1/health reports the scanner as stale past this delay without a cycle.
SCANNER_STALE_AFTER = timedelta(minutes=30)
