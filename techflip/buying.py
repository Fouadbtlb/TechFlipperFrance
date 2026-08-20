"""Budget hunt: the best part you can actually buy for a given budget.

The flip pipeline answers "does this ad make me money". This answers the other
half of a flipper's day: "I have N euros, what is the best card/console I can
get, and is anyone selling one under market". Searches are generated from the
catalog itself, so coverage grows with the pricebook instead of with a
hand-written list of queries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import SearchConfig
from .geo import zone_for_distance
from .pricing.extract import extract_components, _is_bundle

_2EM_URL = ("https://www.2ememain.be/lrp/api/search?query={q}&limit=30&offset=0"
            "&sortBy=SORT_INDEX&sortOrder=DECREASING")

# Cards sold on looks: the white/silver lines carry a real premium, and a buyer
# who wants one will not accept a black card at any price.
WHITE_MARKERS = re.compile(
    r"\b(white|blanc|blanche|wit|witte|vision|aero|snow|frozen|pure)\b", re.I)

# A private seller describes their own card ("acheté en 2022, jamais overclocké").
# Copied spec-sheet marketing means the ad was assembled from the product page,
# which pairs with a press-render photo and an under-market price on bait ads.
_SALES_COPY = re.compile(
    r"experience .*(gaming|performance)|known for its|premium .*(technology|build)"
    r"|boost clock up to|unleash|next-gen(eration)? gaming|immersive gaming", re.I)


def looks_like_sales_copy(text: str) -> bool:
    """Ad text lifted from the manufacturer page rather than written by a seller."""
    t = text or ""
    return bool(_SALES_COPY.search(t)) or t.count("•") >= 3


@dataclass(frozen=True)
class Buy:
    key: str
    label: str
    price: float
    value: float
    discount: float
    zone: str
    distance: float | None
    white: bool
    title: str
    url: str
    city: str | None
    sales_copy: bool = False


def catalog_queries(catalog, category: str) -> list[str]:
    """Search terms for every model of a category the pricebook knows."""
    return [d.label for d in catalog.defs if d.category == category]


def _searches(catalog, category: str, budget: float, broad: tuple[str, ...]) -> list[SearchConfig]:
    terms = list(broad) + catalog_queries(catalog, category)
    return [
        SearchConfig(name=f"{category}:{t}", source="2ememain",
                     url=_2EM_URL.format(q=t.replace(" ", "%20")), kind="hunt",
                     min_price=20, max_price=budget * 1.2)
        for t in terms
    ]


_BROAD = {
    "gpu": ("carte graphique", "videokaart", "grafische kaart"),
    "console": ("console", "spelcomputer"),
    "cpu": ("processeur", "processor"),
    "laptop": ("pc portable", "laptop"),
}


def find_buys(pipeline, category: str, budget: float, stretch: float = 1.0) -> list[Buy]:
    """Every listing of `category` at or under budget, priced by the tracker.

    stretch > 1 also returns slightly-over-budget items, so a 400 EUR card is
    still shown to someone holding 350 rather than silently hidden.
    """
    settings = pipeline.settings
    catalog = pipeline.catalog
    source = pipeline.sources.get("2ememain")
    if source is None:
        from .sources.deuxememain import DeuxiemeMainSource
        source = DeuxiemeMainSource()
    cap = budget * stretch

    seen: dict[str, object] = {}
    for search in _searches(catalog, category, cap, _BROAD.get(category, ())):
        try:
            for l in source.fetch(search):
                seen.setdefault(l.uid, l)
        except Exception:
            continue

    out: list[Buy] = []
    for l in seen.values():
        if not l.price or l.price > cap or _is_bundle(l.title):
            continue
        comps = [c for c in extract_components(l.title.lower(), catalog)
                 if c.category == category]
        if len(comps) != 1:
            continue
        c = comps[0]
        q = pipeline.tracker.price(c.key)
        if q.unit_value is None:
            continue
        distance = pipeline.locator.distance(l.zipcode, l.lat, l.lng)
        out.append(Buy(
            key=c.key, label=c.label, price=l.price, value=q.unit_value,
            discount=round(q.unit_value - l.price, 2),
            zone=zone_for_distance(distance, settings.easy_km, settings.medium_km),
            distance=distance,
            white=bool(WHITE_MARKERS.search(f"{l.title} {l.description or ''}")),
            title=l.title, url=l.url, city=l.city,
            sales_copy=looks_like_sales_copy(l.description),
        ))
    return out


def rank_buys(buys: list[Buy], budget: float, white_only: bool = False) -> list[Buy]:
    """Best hardware first, and among equal hardware the cheapest.

    Anything priced far under its market value is pushed to the back rather than
    shown as a bargain: on a marketplace that gap is a bait ad, not a gift.
    """
    picks = [b for b in buys if b.price <= budget]
    if white_only:
        picks = [b for b in picks if b.white]
    plausible = [b for b in picks if b.price >= 0.45 * b.value]
    return sorted(plausible, key=lambda b: (-b.value, b.price))
