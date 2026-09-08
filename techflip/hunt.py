"""Shopping mode: what is worth BUYING, out of everything ever scraped.

The alert pipeline judges an ad once, in the minute it appears, and only if it
clears a flip margin. That is the wrong shape for how a flipper actually buys.
An ad that has sat for three weeks at a fair price is still a fine purchase; a
tower is worth what its parts are worth whether or not it was posted today; and
"the cheapest Xbox within 60km" is a question with an answer even when no ad
beats the alert bar.

So this module re-reads the whole stored pool with the current pricing rules,
with no date filter and no alert bookkeeping, and ranks it as a shopping list.
Two shapes are priced, where `buying.find_buys` only handled the first:

  single  one recognised item; worth what the tracker says that item is worth.
  build   a tower or bundle; worth the sum of the parts named in it, which is
          the part-out number and the only honest way to judge a PC ad.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from dataclasses import dataclass

from .buying import WHITE_MARKERS, looks_like_sales_copy
from .domain import Listing
from .geo import zone_for_distance
from .pcmarket import PCMarket, cpu_tier
from .pricing.appraise import REALIZATION, appraise, build_items, listing_condition
from .pricing.extract import _is_bundle, _norm, recognize

PC = "pc"

# Source aisles that cannot contain a whole machine. A shop files its stock, and
# "Edition Collector PlayStation 5 Dragon Ball Sparking Zero" (200 EUR) sat in
# /jeux-playstation/ while being valued as a 340 EUR console: nothing in the
# title says "game", but the shop already said it. Substring match, so
# "jeux-xbox-series-x-s" and "accessoires-informatique" are both covered.
_NON_MACHINE_AISLES = ("jeux", "accessoire", "toebehoren", "games")
_MACHINE_CATEGORIES = frozenset({"console", "laptop"})


def _aisle_bars_machines(source_category: str | None) -> bool:
    c = (source_category or "").lower()
    return bool(c) and any(w in c for w in _NON_MACHINE_AISLES)

# Under this share of market value the ad is not a bargain, it is bait: the
# card does not exist, the "PS5" is a photo off Google, payment is by transfer.
# Kept visible but ranked last, because a real 60%-of-market ad does exist and
# hiding the band outright would hide it too.
BAIT_RATIO = 0.45

# A listing not seen in this many days is probably gone. Still shown (the seller
# may simply have dropped off page 1 of a query) but marked, and never ranked
# above something we confirmed alive this morning.
STALE_DAYS = 10

# Still being returned by a search this long after it first appeared means the
# ad has not sold at that price. On the board that is a negotiating position,
# not a warning: the seller has had two weeks of silence and knows it.
SITTING_DAYS = 10

# Nobody writes the motherboard, PSU, case and cooler in a PC ad; the machine
# contains them regardless. Summing only the headline parts therefore priced
# EVERY tower below its asking price -- a 550 EUR "Ryzen 5 5600 + RX 5700XT +
# 16GB" came back at 280 -- which is the single reason no PC ever surfaced as
# worth buying. Each unnamed base part is credited at the catalog's own CHEAPEST
# seed for its category, so the allowance moves with the pricebook instead of
# being a magic number, stays a lower bound, and is only granted to a build that
# actually has a priced CPU or GPU (an empty case is not a computer).
#
# This lives in shopping mode, not in the alert path: it is a credit for parts
# nobody photographed, and a human reads every row on the board before driving
# anywhere. Feeding an unverifiable allowance into automatic alerts is how the
# false positives of 2026-08-12 happened.
CHASSIS_CATEGORIES = ("motherboard", "psu", "case", "cooler")
CHASSIS_LABEL = {"motherboard": "Carte mere", "psu": "Alim",
                 "case": "Boitier", "cooler": "Ventirad"}

_LAPTOP = re.compile(
    r"\b(portable|portables|laptop|notebook|macbook|ultrabook|chromebook)\b", re.IGNORECASE)

# The chip suffix betrays a laptop that never uses the word. "PC Gaming HP OMEN
# Intel i7-13700HX RTX4080", 1300 EUR, topped the shortlist at +400: HX is
# mobile, so its RTX 4080 is the mobile part, worth a fraction of the desktop
# card it shares a name with. H / HX / HS / U only -- never K, F or X, which
# are desktop.
_MOBILE_CPU = re.compile(
    r"\b(?:i[3579]|ryzen\s*[3579])[\s-]*\d{4,5}\s*(?:hx|hs|h|u)\b", re.IGNORECASE)

# Someone looking to BUY, not to sell. "Recherche ps5 standard" ranked third on
# the board, appraised as if it were a PS5 for sale. The alert path drops these
# through `default_exclude` in searches.yaml; the board reads the database
# directly and so never saw that filter.
#
# Title only, and anchored to the front. A wanted ad announces itself in its
# first words; deeper in a title the same verb is ordinary sales copy
# ("PS5 recherchee par tous"), and matching that would bin real offers.
# Stems, not whole words: sellers type "Recherch ps5" and "cherches", and an
# exact-word list misses every typo. Matched against the accent-stripped title,
# because "achète" does not start with the stem "achet".
_WANTED = re.compile(
    r"^\W*(?:recherch\w*|cherch\w*|achet\w*|achat|"
    r"gezocht|zoek\w*|op zoek|gevraagd|wanted|looking for)\b")


@dataclass(frozen=True)
class Find:
    uid: str
    source: str
    title: str
    url: str
    price: float
    value: float                 # realizable resale, after the category haircut
    savings: float               # value - price
    ratio: float                 # value / price
    kind: str                    # "single" | "build"
    category: str                # component category, or "pc" for a build
    parts: tuple[str, ...]
    lines: tuple[str, ...]       # per-part valuation, as shown in alerts
    zone: str
    distance: float | None
    city: str | None
    country: str
    image: str | None
    published_at: str | None
    last_seen: str | None
    age_days: float | None       # days since we last saw it alive
    confidence: float
    n_priced: int
    white: bool
    flags: tuple[str, ...]
    days_listed: float | None = None   # how long it has failed to sell
    price_cut: dict | None = None      # {first, current, cut, pct, changes}
    lat: float | None = None
    lng: float | None = None

    @property
    def is_bait(self) -> bool:
        return "bait" in self.flags

    @property
    def leverage(self) -> str:
        """What to say when you message the seller. The two facts that decide a
        negotiation, and neither was ever shown anywhere in this tool."""
        bits = []
        if self.price_cut:
            bits.append(f"deja baisse de {self.price_cut['cut']:.0f}€ "
                        f"({self.price_cut['pct']:.0%}), il rebaissera")
        if self.days_listed and self.days_listed >= SITTING_DAYS:
            bits.append(f"en vente depuis {self.days_listed:.0f} jours sans partir")
        return " · ".join(bits)


class _CachedTracker:
    """The tracker runs a SQL query per component. Scanning 1500 listings asks
    for the same 120 components over and over, so memoize for the sweep."""

    def __init__(self, tracker):
        self._t = tracker
        self._cache: dict[str, object] = {}

    def price(self, key: str):
        if key not in self._cache:
            self._cache[key] = self._t.price(key)
        return self._cache[key]


def evaluate(
    l: Listing,
    catalog,
    tracker,
    locator,
    *,
    easy_km: float = 60,
    medium_km: float = 150,
    realization: float = 0.85,
    last_seen: str | None = None,
    now: dt.datetime | None = None,
    days_listed: float | None = None,
    price_cut: dict | None = None,
    pc_market=None,
) -> Find | None:
    """Price one listing as a purchase. None when nothing in it can be priced."""
    if not l.price or l.price <= 0:
        return None
    if _WANTED.match(_norm(l.title)):
        return None
    comps = recognize(l.title, l.description, catalog)
    if _aisle_bars_machines(l.source_category):
        comps = [c for c in comps if c.category not in _MACHINE_CATEGORIES]
    if not comps:
        return None

    text = f"{l.title} {l.description or ''}"
    appr = appraise(build_items(comps, None, catalog, text), tracker, realization)
    if appr.n_priced == 0 or appr.true_value <= 0:
        return None

    # "PC portable" carries the token "pc", so a laptop reads as a tower. It has
    # no ATX case, no ATX PSU and no socketed board to credit, and its parts are
    # priced off the desktop pricebook where a mobile RTX 3050 shares a name with
    # a card worth several times as much. Never credited, always flagged.
    # A Switch or a Steam Deck ad says "console portable" because that is what
    # it is. Reading that as a laptop told the reader a 90 EUR console had
    # been priced from desktop part values, which is false and alarming. A
    # recognised console settles it: handhelds are consoles, not laptops.
    laptop = (bool(_LAPTOP.search(text)) or bool(_MOBILE_CPU.search(text))) \
        and not any(c.category == "console" for c in comps)
    build = _is_bundle(l.title) and not laptop
    value, lines = appr.true_value, list(appr.lines)
    if build:
        credit, credit_lines = chassis_allowance(catalog, comps, realization)
        value = round(value + credit, 2)
        lines += credit_lines
        # A tower can be sold whole or stripped for parts, and its owner takes
        # whichever pays more. Valuing it only at part-out is what put EVERY PC
        # near Lille underwater (-64, -107, -143) while those same machines were
        # changing hands at the asking prices: an RTX 3060 tower asks a median
        # of 700 where its parts sum to about 400.
        gpu = next((c for c in comps if c.category == "gpu"), None)
        if pc_market is not None and gpu is not None:
            whole, n = pc_market.whole_value(gpu.key, exclude_uid=l.uid,
                                             cpu=cpu_tier(text))
            if whole is not None:
                lines.append(f"Machine complete comparable ({gpu.label}, "
                             f"{n} annonces): {whole:.0f}\u20ac (marche)")
                if whole > value:
                    value = whole
                    lines.append("-> valorisee en machine complete, pas en pieces")

    distance = locator.distance(l.zipcode, l.lat, l.lng)
    age = _age_days(last_seen, now)
    savings = round(value - l.price, 2)

    flags = []
    if laptop:
        flags.append("laptop")
    if l.price < BAIT_RATIO * value:
        flags.append("bait")
    if listing_condition(None, text) == "broken":
        flags.append("broken")
    if looks_like_sales_copy(l.description):
        flags.append("sales_copy")
    if appr.n_unpriced:
        flags.append("partial")
    if age is not None and age >= STALE_DAYS:
        flags.append("stale")
    if price_cut:
        flags.append("cut")
    if days_listed is not None and days_listed >= SITTING_DAYS:
        flags.append("sitting")

    return Find(
        uid=l.uid, source=l.source, title=l.title, url=l.url, price=float(l.price),
        value=value, savings=savings,
        ratio=round(value / l.price, 3),
        kind="build" if build else "single",
        category=PC if build else comps[0].category,
        parts=tuple(c.label for c in comps),
        lines=tuple(lines),
        zone=zone_for_distance(distance, easy_km, medium_km),
        distance=distance, city=l.city, country=l.country,
        lat=l.lat, lng=l.lng,
        image=l.image_urls[0] if l.image_urls else None,
        published_at=l.published_at, last_seen=last_seen, age_days=age,
        confidence=appr.confidence, n_priced=appr.n_priced,
        white=bool(WHITE_MARKERS.search(text)),
        flags=tuple(flags),
        days_listed=days_listed, price_cut=price_cut,
    )


# Part numbers as sellers actually write them. Used to find what the catalog is
# blind to: a token matching one of these that the recognizer cannot read is a
# real part, in a real ad, being valued at zero.
_PART_SHAPES = {
    "gpu": re.compile(r"\b(?:rtx|gtx|rx|arc)\s*[- ]?\s*a?\d{3,4}\s*(?:ti|xt|xtx|super)?\b", re.IGNORECASE),
    "cpu": re.compile(r"\b(?:i[3579][- ]?\d{4,5}[a-z]{0,2}"
                      r"|ryzen\s*[3579]\s*\d{4}[a-z]{0,3})\b", re.IGNORECASE),
}
# Mobile suffixes. A laptop chip is not a desktop chip at any price, so these
# are reported separately rather than proposed as pricebook entries.
_MOBILE = re.compile(r"\d{3,5}\s*(?:h[xs]?|u|hk)$", re.IGNORECASE)


def gaps(store, catalog, limit: int = 40) -> list[dict]:
    """Parts appearing in stored ads that the catalog cannot recognise.

    This is how the pricebook stops being a guess about what people sell. Every
    unread part silently values a machine at less than it is worth: a tower with
    a GTX 1070 and an i5-6600K, neither in the catalog, was appraised on its RAM
    alone. Run it, add the top rows to config/pricebook.yaml, run `retrack`.
    """
    from collections import Counter

    from .pricing.extract import extract_components

    seen = Counter()
    examples: dict[tuple, str] = {}
    for row in store.all_listings():
        try:
            d = json.loads(row["raw_json"])
        except (ValueError, TypeError):
            continue
        text = f"{d.get('title') or ''} {d.get('description') or ''}"
        for kind, rx in _PART_SHAPES.items():
            for m in rx.finditer(text):
                tok = " ".join(m.group(0).split()).lower()
                if extract_components(tok, catalog):
                    continue
                key = (kind, tok)
                seen[key] += 1
                examples.setdefault(key, (d.get("title") or "")[:60])
    return [{"kind": k, "token": t, "n": n, "mobile": bool(_MOBILE.search(t)),
             "example": examples[(k, t)]}
            for (k, t), n in seen.most_common(limit)]


_2EM_URL = ("https://www.2ememain.be/lrp/api/search?query={q}&limit=30&offset=0"
            "&sortBy=SORT_INDEX&sortOrder=DECREASING")
_LBC_URL = "https://www.leboncoin.fr/recherche?text={q}"

# Leboncoin categories, so a query for "xbox" returns consoles and not five
# pages of games: 43 = Consoles & jeux video, 15 = Informatique.
_LBC_CATEGORY = {"console": 43, "pc": 15, "gpu": 15, "cpu": 15}


def sweep(pipeline, terms, *, max_price: float | None = None,
          category: str | None = None, pages: int = 1) -> dict:
    """Go and look, now, for these terms on every configured source.

    The loop only ever polls its fixed searches, so a question it was never
    configured for ("an Xbox under 150") can only be answered out of whatever
    the pool happens to hold. This runs the query for real and ingests the
    results, which the board then prices like any other row.

    Ingest only: nothing here alerts, marks, or writes off a listing. The board
    is a place to look, not a second notifier.
    """
    from .config import SearchConfig

    stats = {"fetched": 0, "new": 0, "errors": 0, "queries": 0}
    lbc_cat = _LBC_CATEGORY.get(category or "", None)
    for term in terms:
        q = term.strip()
        if not q:
            continue
        enc = q.replace(" ", "%20")
        plans = [("2ememain", _2EM_URL.format(q=enc))]
        if "leboncoin" in pipeline.sources:
            url = _LBC_URL.format(q=enc)
            if lbc_cat:
                url += f"&category={lbc_cat}"
            plans.append(("leboncoin", url))

        for source_name, url in plans:
            source = pipeline.sources.get(source_name)
            if source is None:
                continue
            search = SearchConfig(name=f"hunt:{q}", url=url, source=source_name,
                                  kind="feeder", min_price=1, max_price=max_price)
            stats["queries"] += 1
            for page in range(1, pages + 1):
                try:
                    listings = source.fetch(search, page=page)
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    break
                stats["fetched"] += len(listings)
                for l in listings:
                    if pipeline._ingest(l)[0]:
                        stats["new"] += 1
                if len(listings) < 10:
                    break
    return stats


def chassis_allowance(catalog, comps, realization: float = 0.85):
    """Value of the base parts a tower has but its ad never lists.

    Returns (euros, lines). Zero unless the build has a CPU or GPU: that is what
    makes it a computer rather than an empty case or a bag of RAM, and it keeps
    the credit off ads too vague to be worth anything.
    """
    present = {c.category for c in comps}
    if not present & {"cpu", "gpu"}:
        return 0.0, []
    total = 0.0
    lines = []
    for cat in CHASSIS_CATEGORIES:
        if cat in present:
            continue                       # the ad named it, appraise already paid
        seed = _floor_seed(catalog, cat)
        if seed is None:
            continue
        val = seed * REALIZATION.get(cat, realization)
        total += val
        lines.append(f"{CHASSIS_LABEL[cat]} (chassis, non listé): {val:.0f}€ (estim)")
    return round(total, 2), lines


def _floor_seed(catalog, category: str) -> float | None:
    """The cheapest thing in the category, not the typical one.

    An unnamed part is an unknown part, and the seller who does not say which
    board is in the machine is not hiding an X670. Crediting the median made
    spelling out a cheap B550 *lower* an ad's value, which is backwards, and
    quietly invented margin on every vague ad. The floor makes the credit a
    lower bound, which is the only version of it safe to act on.
    """
    seeds = [d.seed for d in catalog.defs if d.category == category and d.seed]
    return min(seeds) if seeds else None


def scan(store, catalog, tracker, locator, **kw) -> list[Find]:
    """Price the entire stored pool as a shopping list."""
    cached = _CachedTracker(tracker)
    now = dt.datetime.now(dt.timezone.utc)
    # Both fetched once for the whole pool: a per-listing lookup turns a two
    # second scan into a minute.
    ages = store.market_ages()
    drops = store.price_drops()
    market = PCMarket.from_store(store, catalog)
    out: list[Find] = []
    for row in store.all_listings():
        try:
            l = Listing.from_dict(json.loads(row["raw_json"]))
        except (ValueError, TypeError):
            continue
        f = evaluate(l, catalog, cached, locator,
                     last_seen=row["last_seen"], now=now,
                     days_listed=ages.get(l.uid), price_cut=drops.get(l.uid),
                     pc_market=market, **kw)
        if f is not None:
            out.append(f)
    return out


def filter_finds(
    finds,
    *,
    budget: float | None = None,
    category: str | None = None,
    max_km: float | None = None,
    min_savings: float | None = None,
    kind: str | None = None,
    query: str | None = None,
    max_age_days: float | None = None,
    white_only: bool = False,
    hide_broken: bool = False,
    min_confidence: float | None = None,
    ulat: float | None = None,
    ulng: float | None = None,
    urad: float | None = None,
) -> list[Find]:
    """Narrow the list, preserving order. Every argument is optional so the web
    board can pass whatever the form happened to set."""
    from .geo import haversine
    terms = [t for t in (query or "").lower().split() if t]
    out = []
    for f in finds:
        if budget is not None and f.price > budget:
            continue
        if category and f.category != category:
            continue
        if kind and f.kind != kind:
            continue
        # Unknown distance means we could not place it, which is not the same as
        # "far": excluding it under a radius filter is the safe reading.
        if max_km is not None and (f.distance is None or f.distance > max_km):
            continue
        if min_savings is not None and f.savings < min_savings:
            continue
        if max_age_days is not None and f.age_days is not None and f.age_days > max_age_days:
            continue
        # Confidence is the share of the value backed by prices actually seen on
        # the market rather than by a seed I typed into the pricebook. A margin
        # computed entirely from seeds is a margin against my own guess.
        if min_confidence is not None and f.confidence < min_confidence:
            continue
        if white_only and not f.white:
            continue
        if hide_broken and "broken" in f.flags:
            continue
        if ulat is not None and ulng is not None and urad is not None:
            if f.lat is None or f.lng is None:
                continue
            if haversine(ulat, ulng, f.lat, f.lng) > urad:
                continue
        if terms:
            hay = f"{f.title} {' '.join(f.parts)} {f.city or ''}".lower()
            if not all(t in hay for t in terms):
                continue
        out.append(f)
    return out


SORTS = ("savings", "ratio", "price", "distance", "recent", "value",
         "cut", "sitting")


def rank(finds, sort: str = "savings") -> list[Find]:
    """Order the shopping list. Bait always sinks, whatever the sort.

    Sorting a marketplace by raw discount puts the scams on top every single
    time: the fake listing is the one priced at a third of market. So the band
    is partitioned out first and the honest offers are ordered inside it.
    """
    def key(f: Find):
        if sort == "ratio":
            return (-f.ratio, f.price)
        if sort == "price":
            return (f.price, -f.savings)
        if sort == "distance":
            return (f.distance if f.distance is not None else math.inf, -f.savings)
        if sort == "recent":
            return (f.age_days if f.age_days is not None else math.inf, -f.savings)
        if sort == "value":
            return (-f.value, f.price)
        if sort == "cut":
            # Biggest climb-down first: this seller has already shown they bend.
            return (-(f.price_cut or {}).get("cut", 0), -f.savings)
        if sort == "sitting":
            return (-(f.days_listed or 0), -f.savings)
        return (-f.savings, f.price)

    honest = sorted((f for f in finds if not f.is_bait), key=key)
    bait = sorted((f for f in finds if f.is_bait), key=key)
    return honest + bait


def categories(finds) -> list[tuple[str, int]]:
    """Categories present, most-populated first, for the filter dropdown."""
    counts: dict[str, int] = {}
    for f in finds:
        counts[f.category] = counts.get(f.category, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def _age_days(last_seen: str | None, now: dt.datetime | None) -> float | None:
    if not last_seen:
        return None
    try:
        seen = dt.datetime.fromisoformat(last_seen)
    except ValueError:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return round((now - seen).total_seconds() / 86400, 2)
