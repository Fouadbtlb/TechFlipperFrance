"""Recognize catalog components inside a listing's text.

Cheap, text-only, no network. Runs on every listing at store time so the price
tracker can learn from single-item listings, and gives a first-pass component
list for appraisal. The LLM pass (deal candidates only) refines quantities and
condition on top of this.
"""
from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass

from .catalog import Catalog


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    category: str
    qty: int = 1


def extract_components(text: str, catalog: Catalog) -> list[Component]:
    if not text:
        return []
    consumed: list[tuple[int, int]] = []
    out: list[Component] = []
    seen: set[str] = set()
    for d in catalog.ordered():
        span = _first_free_match(d.patterns, text, consumed)
        if span is None:
            continue
        consumed.append(span)
        if d.key not in seen:
            seen.add(d.key)
            out.append(Component(d.key, d.label, d.category))
    return out


# A machine has one GPU/CPU/motherboard/etc. A description that lists several
# is almost always marketing copy or comparisons ("mieux qu'une RTX 3050"), not
# real contents. So high-value categories are capped: trust the title, and drop
# them entirely when only the description mentions several.
_STRICT = {"gpu", "cpu", "motherboard", "laptop"}
_CAP1 = {"ram", "storage", "psu", "monitor"}
_TITLE_ONLY = {"console"}


_BUNDLE_TOKENS = {"pc", "tour", "setup", "ordinateur", "config", "lot",
                  "bundle", "unite", "unité", "combo", "pack", "desktop",
                  "rig", "workstation", "ordi"}
# Dutch and German glue the words together ("gamepc", "gamingpc", "spielerechner"),
# so the token set alone missed whole towers and let a 1500 EUR machine set the
# price of the single card named in its title.
_MACHINE_COMPOUND = re.compile(r"\w*(?:pc|rechner)$")


def _is_bundle(title: str) -> bool:
    """Whether the ad sells a whole machine rather than one part.

    Word order settles it, the same way it settles `_console_is_subject`: what
    is named first is what is for sale. "Manette SCUF pc ps5 Xbox" lists "pc"
    as a compatibility, not as the item, and reading it as a tower both filled
    the PC shopping board with 100 EUR gamepads and licensed the description to
    be mined for parts the ad never contained. "PC gamer + manette" is the same
    two words the other way round, and really is a tower.
    """
    toks = [t for t in re.split(r"[^0-9a-zà-ÿ]+", (title or "").lower()) if t]
    machine = next(
        (i for i, t in enumerate(toks)
         if t in _BUNDLE_TOKENS or (len(t) > 2 and _MACHINE_COMPOUND.fullmatch(t))),
        None,
    )
    if machine is None:
        return False
    acc = next((i for i, t in enumerate(toks) if t in _ACCESSORY_WORDS), None)
    return acc is None or machine < acc


# Words that mark the ad as selling media or an add-on FOR a machine rather than
# the machine itself. The word-order test below cannot settle these: French puts
# the add-on first ("manette PS5") but Dutch and English put it last ("Switch
# game", "PS5 controllers"), and the Belgian pool is full of both. A listing
# carrying any of these is barred from teaching a price, whichever side it sits
# on -- an ad for four Switch games was pricing the console itself at 90 EUR.
# Note this gate is only about learning: valuing a genuine "PS5 + manette"
# bundle still works, it simply never sets the reference price.
_NOT_THE_MACHINE = {
    "game", "games", "spel", "spellen", "spelletje", "spelletjes", "jeu", "jeux",
    "cd", "cds", "dvd", "controller", "controllers", "manette", "manettes",
    "housse", "hoes", "coque", "sacoche", "sticker", "stickers", "cover",
    "chargeur", "charger", "oplader", "cable", "câble", "kabel", "dock",
    "docking", "socle", "station", "support", "grip", "casque", "abonnement",
    "accessoire", "accessoires", "toebehoren", "protection", "volant",
    # pad brands: an ad titled only "Scuf Reflex ... ps5" is a pad, not a console
    "scuf", "nacon", "dualsense", "dualshock", "joycon",
}


def teaches_price(title: str) -> bool:
    """Whether this ad may set a component's reference price. Stricter than
    recognition on purpose: a poisoned median is worse than a missed sample."""
    toks = set(re.split(r"[^0-9a-zà-ÿ]+", (title or "").lower()))
    return not (toks & _NOT_THE_MACHINE)


_CONSOLE_WORDS = {"ps5", "ps4", "ps3", "playstation", "xbox", "switch", "console", "wii"}
_ACCESSORY_WORDS = {"manette", "manettes", "casque", "support", "telecommande",
                    "télécommande", "cable", "câble", "chargeur", "housse", "sacoche",
                    "socle", "station", "coque", "protection", "volant", "jeu", "jeux",
                    "simulateur", "pedales", "pédales", "pedalier",
                    "sticker", "stickers", "grip", "facade", "façade", "abonnement",
                    # An empty case is a part, never the machine: "Boitier PC ...
                    # 10 ventilateur" was being appraised as a whole tower.
                    "boitier", "boîtier", "ventilateur", "ventilateurs"}


# Nouns that are never the machine, wherever they sit in the title. The
# positional test below settles French ("manette PS5"), but English and Dutch
# put the console name FIRST and still sell an accessory: "2 Ps5 30th
# Anniversary Limited Edition controllers" was appraised as a 368 EUR console.
_ADDON_NOUNS = {
    "controller", "controllers", "manette", "manettes", "spel", "spellen",
    "spelletje", "spelletjes", "jeu", "jeux", "game", "games", "housse", "hoes",
    "coque", "sacoche", "chargeur", "charger", "oplader", "kabel", "kabels",
    "casque", "sticker", "stickers", "volant", "pedales", "pédales",
    # A drive sold FOR a console is not the console: "SSD ps5 2TO" (300 EUR,
    # Lille) was appraised as a 368 EUR PS5.
    # NB not "disque" alone: "PS5 edition disque" is the disc console itself.
    "ssd", "nvme", "hdd", "dur", "schijf", "harde",
    # A headset is an accessory however a shop titles it: "ps vr 2 ps5",
    # 250 EUR at Cash Converters, was appraised as a 340 EUR PS5.
    "vr", "psvr", "vr2",
    # Pad names, which `_NOT_THE_MACHINE` already blocks from teaching a
    # price but which were not barred from BEING the machine: "Console
    # NINTENDO Switch (Joycon Gauche uniquement)" was valued as a console.
    "joycon", "joycons", "dualsense", "dualshock", "scuf", "nacon",
}
# ...unless the ad also says it is selling the machine those extras come with.
_BUNDLE_MARKERS = {"console", "avec", "met", "inclus", "incl", "included",
                   "complet", "complete", "compleet", "bundle", "pack", "+"}
# ...and these cancel the bundle markers again. A pro shop states the
# shortfall in the title: "Console NINTENDO Switch Chargeur Uniquement" is a
# charger. The word "console" alone made that read as a bundle, so it was
# valued at 161 EUR as a whole machine.
_ONLY_WORDS = {"uniquement", "seul", "seule", "seulement", "only", "alleen",
               "enkel", "sans"}


def _console_is_subject(title: str) -> bool:
    t = (title or "").lower()
    toks = [x for x in re.split(r"[^0-9a-zà-ÿ]+", t) if x]
    con = next((i for i, x in enumerate(toks) if x in _CONSOLE_WORDS), None)
    if con is None:
        return True
    # Position-independent: an accessory noun with nothing saying a machine is
    # included means the accessory is what is for sale, whatever the word order.
    addon = set(toks) & _ADDON_NOUNS
    bundle = "+" in t or set(toks) & _BUNDLE_MARKERS
    if addon and (not bundle or set(toks) & _ONLY_WORDS):
        return False
    acc = next((i for i, x in enumerate(toks) if x in _ACCESSORY_WORDS), None)
    return acc is None or con < acc


# A bare title ("Ps5", "Nintendo Switch") names a family, not a model, and the
# cheaper sibling is usually spelled out in the description instead. Each entry
# maps an ambiguous key to the markers that pin it to a CHEAPER variant. Only
# downward moves are listed on purpose: reading the description can then correct
# an over-valuation but can never invent one, which is what keeps a
# compatibility list ("mieux qu'une PS5 Pro") from upgrading the item.
_VARIANTS: dict[str, tuple[tuple[re.Pattern, str], ...]] = {
    "console:ps5": (
        # "ps5 portable" is how sellers write the PlayStation Portal handheld
        # (~170), and it was being valued as a 420 EUR console. Checked before
        # the disc/digital split because a Portal is neither.
        (re.compile(r"\bportable\b"), "console:ps-portal"),
        (re.compile(r"\b(digital|digitale|digiale|numerique|sans lecteur)\b"),
         "console:ps5-digital"),
    ),
    "console:switch": (
        (re.compile(r"\blite\b"), "console:switch-lite"),
        (re.compile(r"\boled\b"), "console:switch-oled"),
    ),
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def refine_variant(comp: Component, text: str, catalog: Catalog) -> Component:
    """Pin an ambiguous family key to the cheaper model the text spells out."""
    rules = _VARIANTS.get(comp.key)
    if not rules:
        return comp
    t = _norm(text)
    for rx, key in rules:
        d = catalog.by_key.get(key)
        if d and rx.search(t):
            return Component(d.key, d.label, d.category, comp.qty)
    return comp


def recognize(title: str, description: str, catalog: Catalog) -> list[Component]:
    title_comps = extract_components(title or "", catalog)
    # Only a whole-machine/bundle listing absorbs parts named in its description.
    # A single-item sale ("RTX 4070 videokaart", "manette PS5") is valued on its
    # title alone, so context/compatibility mentions can't inflate it.
    if _is_bundle(title):
        all_comps = extract_components(f"{title or ''} {description or ''}", catalog)
    else:
        all_comps = title_comps

    title_by_cat: dict[str, list[Component]] = {}
    for c in title_comps:
        title_by_cat.setdefault(c.category, []).append(c)
    all_by_cat: dict[str, list[Component]] = {}
    for c in all_comps:
        all_by_cat.setdefault(c.category, []).append(c)

    out: list[Component] = []
    for cat, comps in all_by_cat.items():
        title_comps_cat = title_by_cat.get(cat, [])
        if cat in _TITLE_ONLY:
            if title_comps_cat and _console_is_subject(title):
                out.append(title_comps_cat[0])
        elif cat in _STRICT:
            if title_comps_cat:
                out.append(title_comps_cat[0])
            elif len(comps) == 1:
                out.append(comps[0])
        elif cat in _CAP1:
            out.append(title_comps_cat[0] if title_comps_cat else comps[0])
        else:
            out.extend(comps)
    full = f"{title or ''} {description or ''}"
    return [refine_variant(c, full, catalog) for c in out]


def primary_key(components: list[Component]) -> str | None:
    """The key when the listing is a single recognized item, else None.

    Only single-item listings teach the tracker a clean per-component price.
    """
    return components[0].key if len(components) == 1 else None


# Generic console keys whose bare title hides a materially cheaper look-alike,
# with the tokens that would confirm the pricier reading. Matched generic with
# none of those tokens in the title means the value can't be trusted from text:
#   switch : a plain "Nintendo Switch" is often the cheaper Lite (105 vs 160);
#            no bare-title token confirms the full model, so it is always unsure.
#   ps5    : a bare "PS5" can be the Digital (~60 EUR less); only an explicit
#            disc/standard mention confirms the pricier disc model.
_AMBIGUOUS_CONSOLE = {
    "console:switch": (),
    "console:ps5": ("disque", "disc", "standard"),
}


def is_ambiguous_identity(components: list[Component], title: str) -> bool:
    """True when the single recognized item could be a cheaper variant that the
    title doesn't rule out, so its optimistic value must not alert unverified."""
    markers = _AMBIGUOUS_CONSOLE.get(primary_key(components))
    if markers is None:
        return False
    t = (title or "").lower()
    return not any(m in t for m in markers)


def _first_free_match(patterns, text, consumed) -> tuple[int, int] | None:
    for rx in patterns:
        for m in rx.finditer(text):
            if not _overlaps(m.span(), consumed):
                return m.span()
    return None


def _overlaps(span, spans) -> bool:
    a, b = span
    return any(not (b <= x or a >= y) for x, y in spans)
