"""Shopping mode: what is worth BUYING, out of everything stored.

The scanner judges an ad in the minute it appears, and alerts only if it clears
a flip margin. That is the wrong shape for how a flipper actually buys: an ad
that has sat for three weeks at a fair price is still a fine purchase, and "the
cheapest Xbox within 60 km" has an answer even when no ad beats the alert bar.

So this re-reads the whole pool still online with the current pricing rules,
no date filter and no alert bookkeeping, and ranks it as a shopping list for
the local board (web.py) and `cli find`. Two shapes are priced:

  single  one recognized item, worth what the tracker says it is worth;
  build   a tower or bundle, worth the higher of its parts (plus the base
          parts every tower has but no ad lists) and what comparable whole
          towers ask.

`savings` is what is left after the trip: value - price - the cheaper of the
round-trip drive (COST_PER_KM) and shipping. A human reads every row before
driving anywhere, which is why the board may credit unlisted parts that the
scanner never would.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from dataclasses import dataclass

from . import tuning
from .domain import Listing
from .filters import not_an_offer
from .geo import haversine, logistics_cost, zone_for_distance
from .pcmarket import PCMarket, cpu_tier
from .pricing.appraise import REALIZATION, appraise, build_items, listing_condition
from .pricing.extract import extract_components, is_bundle
from .pricing.identify import carrier_locked, components_of, is_laptop, is_part_aisle
from .valuation import is_shippable

PC = "pc"

# Under BAIT_RATIO of market value the ad is not a bargain, it is bait: the card
# does not exist, the "PS5" is a photo off Google. Kept visible but ranked last,
# because a real 60 %-of-market ad does exist. Not seen for STALE_DAYS: probably
# gone. Still online SITTING_DAYS after it appeared: it has not sold at that
# price, which is a negotiating position.
BAIT_RATIO = tuning.BOARD_BAIT_RATIO
STALE_DAYS = tuning.BOARD_STALE_DAYS
SITTING_DAYS = tuning.BOARD_SITTING_DAYS

# Nobody writes the motherboard, PSU, case and cooler in a PC ad; the machine
# contains them regardless. Summing only the headline parts priced every tower
# below its asking price. Each unnamed base part is credited at the catalog's
# CHEAPEST seed for its category: a lower bound, and only for a build that has
# a priced CPU or GPU (an empty case is not a computer).
CHASSIS_CATEGORIES = ("motherboard", "psu", "case", "cooler")
CHASSIS_LABEL = {"motherboard": "Carte mere", "psu": "Alim", "case": "Boitier", "cooler": "Ventirad"}

# White/silver cards carry a real premium for the buyer who wants one.
WHITE_MARKERS = re.compile(r"\b(white|blanc|blanche|wit|witte|vision|aero|snow|frozen|pure)\b", re.I)
# Spec-sheet marketing instead of a seller's own words: pairs with a press
# render and an under-market price on bait ads.
_SALES_COPY = re.compile(
    r"experience .*(gaming|performance)|known for its|premium .*(technology|build)"
    r"|boost clock up to|unleash|next-gen(eration)? gaming|immersive gaming", re.I)


def looks_like_sales_copy(text: str | None) -> bool:
    t = text or ""
    return bool(_SALES_COPY.search(t)) or t.count("•") >= 3


@dataclass(frozen=True)
class Find:
    uid: str
    source: str
    title: str
    url: str
    price: float
    value: float                 # realizable resale, after the category haircut
    savings: float               # value - price - trip
    ratio: float                 # value / price
    kind: str                    # "single" | "build"
    category: str                # component category, or "pc" for a build
    parts: tuple[str, ...]
    lines: tuple[str, ...]       # per-part valuation, as shown in alerts
    zone: str
    distance: float | None
    trip: float | None           # cheaper of the round-trip drive and shipping
    city: str | None
    country: str
    image: str | None
    published_at: str | None
    last_seen: str | None
    age_days: float | None       # days since we last saw it online
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
        """What to say when you message the seller."""
        bits = []
        if self.price_cut:
            bits.append(f"deja baisse de {self.price_cut['cut']:.0f}€ "
                        f"({self.price_cut['pct']:.0%}), il rebaissera")
        if self.days_listed and self.days_listed >= SITTING_DAYS:
            bits.append(f"en vente depuis {self.days_listed:.0f} jours sans partir")
        return " · ".join(bits)


class _CachedTracker:
    """Scanning 1500 listings asks for the same 120 components over and over.
    The one exception is a single item priced against its own component: it
    must stay out of its own comparables, so that call is not shared.
    `teaches`: uid -> the component that listing teaches."""

    def __init__(self, tracker, teaches: dict[str, str]):
        self._t = tracker
        self._teaches = teaches
        self._cache: dict[str, object] = {}

    def price(self, key: str, exclude_uid: str | None = None):
        if exclude_uid and self._teaches.get(exclude_uid) == key:
            return self._t.price(key, exclude_uid)
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
    cost_per_km: float = 0.25,
    last_seen: str | None = None,
    now: dt.datetime | None = None,
    days_listed: float | None = None,
    price_cut: dict | None = None,
    pc_market=None,
) -> Find | None:
    """Price one listing as a purchase. None when it is not an offer or nothing
    in it can be priced."""
    if not l.price or l.price <= 0:
        return None
    comps = components_of(l, catalog)
    if not comps or not_an_offer(l, comps):
        return None

    text = f"{l.title} {l.description or ''}"
    appr = appraise(build_items(comps, None, catalog, text, l.title), tracker, realization, l.uid)
    if appr.n_priced == 0 or appr.true_value <= 0:
        return None

    laptop = is_laptop(text, comps)
    build = is_bundle(l.title) and not laptop and not is_part_aisle(l.source_category)
    value, lines = appr.true_value, list(appr.lines)
    if build:
        credit, credit_lines = chassis_allowance(catalog, comps, realization)
        value = round(value + credit, 2)
        lines += credit_lines
        # A tower sells whole or stripped for parts, whichever pays more: an
        # RTX 3060 tower asks a median of 700 where its parts sum to about 400.
        gpu = next((c for c in comps if c.category == "gpu"), None)
        if pc_market is not None and gpu is not None:
            whole, n = pc_market.whole_value(gpu.key, exclude_uid=l.uid, cpu=cpu_tier(text))
            if whole is not None:
                lines.append(f"Machine complete comparable ({gpu.label}, {n} annonces): {whole:.0f}€ (marche)")
                if whole > value:
                    value = whole
                    lines.append("-> valorisee en machine complete, pas en pieces")

    distance = locator.distance(l.zipcode, l.lat, l.lng)
    ship_class = "bulky" if build else catalog.by_key[comps[0].key].ship_class
    # A shop sells at its counter.
    trip = logistics_cost(distance, ship_class, l.owner_type != "pro" and is_shippable(l.description),
                          cost_per_km)
    savings = round(value - l.price - (trip or 0), 2)
    age = _age_days(last_seen, now)

    flags = []
    if laptop:
        flags.append("laptop")
    if l.price < BAIT_RATIO * value:
        flags.append("bait")
    if listing_condition(None, text, l.title) == "broken":
        flags.append("broken")
    if carrier_locked(text):
        flags.append("locked")
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
        value=value, savings=savings, ratio=round(value / l.price, 3),
        kind="build" if build else "single",
        category=PC if build else comps[0].category,
        parts=tuple(c.label for c in comps), lines=tuple(lines),
        zone=zone_for_distance(distance, easy_km, medium_km),
        distance=distance, trip=trip, city=l.city, country=l.country, lat=l.lat, lng=l.lng,
        image=l.image_urls[0] if l.image_urls else None,
        published_at=l.published_at, last_seen=last_seen, age_days=age,
        confidence=appr.confidence, n_priced=appr.n_priced,
        white=bool(WHITE_MARKERS.search(text)), flags=tuple(flags),
        days_listed=days_listed, price_cut=price_cut,
    )


def chassis_allowance(catalog, comps, realization: float = 0.85):
    """Value of the base parts a tower has but its ad never lists: (euros, lines).
    Zero unless the build has a CPU or GPU."""
    present = {c.category for c in comps}
    if not present & {"cpu", "gpu"}:
        return 0.0, []
    total, lines = 0.0, []
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
    """The cheapest seed in the category: a seller who does not say which board
    is in the machine is not hiding an X670."""
    seeds = [d.seed for d in catalog.defs if d.category == category and d.seed]
    return min(seeds) if seeds else None


def scan(store, catalog, tracker, locator, **kw) -> list[Find]:
    """Price the whole pool still online as a shopping list."""
    rows = store.active_listings()
    cached = _CachedTracker(tracker, {r["uid"]: r["primary_component"] for r in rows if r["primary_component"]})
    now = dt.datetime.now(dt.timezone.utc)
    ages = store.market_ages()
    cuts = store.price_cuts()
    market = PCMarket.from_store(store, catalog)
    out: list[Find] = []
    for row in rows:
        try:
            l = Listing.from_dict(json.loads(row["raw_json"]))
        except (ValueError, TypeError):
            continue
        f = evaluate(l, catalog, cached, locator, last_seen=row["last_seen"], now=now,
                     days_listed=ages.get(l.uid), price_cut=cuts.get(l.uid), pc_market=market, **kw)
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
    """Narrow the list, preserving order. Every argument is optional."""
    terms = [t for t in (query or "").lower().split() if t]
    out = []
    for f in finds:
        if budget is not None and f.price > budget:
            continue
        if category and f.category != category:
            continue
        if kind and f.kind != kind:
            continue
        # Unknown distance is not "far", but under a radius filter excluding it
        # is the safe reading.
        if max_km is not None and (f.distance is None or f.distance > max_km):
            continue
        if min_savings is not None and f.savings < min_savings:
            continue
        if max_age_days is not None and f.age_days is not None and f.age_days > max_age_days:
            continue
        # Confidence is the share of the value backed by prices seen on the
        # market rather than by a seed typed into the pricebook.
        if min_confidence is not None and f.confidence < min_confidence:
            continue
        if white_only and not f.white:
            continue
        if hide_broken and "broken" in f.flags:
            continue
        if None not in (ulat, ulng, urad) and (
                f.lat is None or f.lng is None or haversine(ulat, ulng, f.lat, f.lng) > urad):
            continue
        if terms:
            hay = f"{f.title} {' '.join(f.parts)} {f.city or ''}".lower()
            if not all(t in hay for t in terms):
                continue
        out.append(f)
    return out


SORTS = ("savings", "ratio", "price", "distance", "recent", "value", "cut", "sitting")


def rank(finds, sort: str = "savings") -> list[Find]:
    """Order the shopping list. Bait always sinks, whatever the sort: sorting a
    marketplace by raw discount puts the scams on top every time."""
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


# ---------------------------------------------------------------- going to look

_2EM_URL = ("https://www.2ememain.be/lrp/api/search?query={q}&limit=30&offset=0"
            "&sortBy=SORT_INDEX&sortOrder=DECREASING")
_LBC_URL = "https://www.leboncoin.fr/recherche?text={q}"
# 43 = Consoles & jeux video, 15 = Informatique: "xbox" returns consoles, not games.
_LBC_CATEGORY = {"console": 43, "pc": 15, "gpu": 15, "cpu": 15}


# Broad terms for a live look at a whole category (`cli buy --live`).
BROAD_TERMS = {
    "gpu": ("carte graphique", "rtx", "videokaart"),
    "console": ("console", "ps5", "xbox series", "nintendo switch"),
    "cpu": ("processeur", "ryzen"),
    "pc": ("pc gamer", "gaming pc"),
}


def sweep(pipeline, terms, *, max_price: float | None = None, category: str | None = None,
          pages: int = 1) -> dict:
    """Search these terms now on Leboncoin and 2ememain, and store what comes
    back for the board to price. Ingest only: nothing here alerts. A site that
    blocks or fails is left alone for the rest of the sweep."""
    from .config import SearchConfig

    stats = {"fetched": 0, "new": 0, "errors": 0, "queries": 0}
    failed: set[str] = set()
    lbc_cat = _LBC_CATEGORY.get(category or "")
    for term in terms:
        q = term.strip()
        if not q:
            continue
        lbc_url = _LBC_URL.format(q=q) + (f"&category={lbc_cat}" if lbc_cat else "")
        for source_name, url in (("2ememain", _2EM_URL.format(q=q.replace(" ", "%20"))),
                                 ("leboncoin", lbc_url)):
            if source_name in failed:
                continue
            source = pipeline.sources.get(source_name)
            if source is None:
                from .pipeline import _make_source
                source = pipeline.sources[source_name] = _make_source(source_name, pipeline.settings)
            search = SearchConfig(name=f"hunt:{q}", url=url, source=source_name, kind="feeder",
                                  min_price=1, max_price=max_price)
            stats["queries"] += 1
            for page in range(1, pages + 1):
                try:
                    listings = source.fetch(search, page=page)
                except Exception:
                    stats["errors"] += 1
                    failed.add(source_name)
                    break
                stats["fetched"] += len(listings)
                stats["new"] += sum(1 for l in listings if pipeline._ingest(l)[0])
                if len(listings) < 10:
                    break
    return stats


# Part numbers as sellers write them: a token matching one of these that the
# recognizer cannot read is a real part being valued at zero.
_PART_SHAPES = {
    "gpu": re.compile(r"\b(?:rtx|gtx|rx|arc)\s*[- ]?\s*a?\d{3,4}\s*(?:ti|xt|xtx|super)?\b", re.I),
    "cpu": re.compile(r"\b(?:i[3579][- ]?\d{4,5}[a-z]{0,2}|ryzen\s*[3579]\s*\d{4}[a-z]{0,3})\b", re.I),
}
# Mobile suffixes: a laptop chip is not a desktop chip, so these are reported
# apart rather than proposed as pricebook entries.
_MOBILE = re.compile(r"\d{3,5}\s*(?:h[xs]?|u|hk)$", re.I)


def gaps(store, catalog, limit: int = 40) -> list[dict]:
    """Parts appearing in stored ads that the catalog cannot recognize, most
    frequent first. Add the top ones to config/pricebook.yaml, then `retrack`."""
    from collections import Counter

    seen: Counter = Counter()
    examples: dict[tuple, str] = {}
    for row in store.active_listings():
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
                seen[(kind, tok)] += 1
                examples.setdefault((kind, tok), (d.get("title") or "")[:60])
    return [{"kind": k, "token": t, "n": n, "mobile": bool(_MOBILE.search(t)), "example": examples[(k, t)]}
            for (k, t), n in seen.most_common(limit)]


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
