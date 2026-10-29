"""What a listing is really selling, beyond the words of its title.

`extract.recognize` reads parts out of text. This module adds what the text
alone gets wrong, learned from real ads:

- the aisle a shop filed it under: a "PlayStation 5" under /jeux-playstation/
  is a game, a "Galaxy S26" under /housses-coques/ is a case;
- laptops that never say "laptop": an "i7-13700HX" or a "Legion" is a laptop,
  and its RTX 4070 is the mobile chip, worth far less than the desktop card;
- which single listings may teach the tracker a part's market price
  (`teaching_key`), the one rule every writer of `primary_component` uses;
- carrier locks, which make a phone sellable only to that network's customers.
"""
from __future__ import annotations

import re

from ..domain import Listing
from ..text import plain
from .catalog import Catalog
from .extract import Component, is_bundle, primary_key, recognize, teaches_price

# Aisles that cannot contain a whole machine (substring match on the aisle).
# "Edition Collector PlayStation 5" (200 EUR) sat in /jeux-playstation/;
# "Samsung Galaxy S26" (400 EUR) in /housses-coques-facades-samsung/;
# "mikrotik switch crs125" in /commutateurs-reseau/.
_NON_MACHINE_AISLES = ("jeux", "accessoire", "toebehoren", "games",
                       "housse", "coque", "hoesje", "reseau", "netwerk")
MACHINE_CATEGORIES = frozenset({"console", "laptop", "phone"})

# Aisles that hold single components. "Gigabyte GeForce RTX 3080 PC de jeu 10G"
# sat in /cartes-video/: a card, whatever "PC de jeu" suggests.
_PART_AISLES = ("cartes-video", "carte-graphique", "cartes-graphiques",
                "composants", "processeur", "memoire")

_LAPTOP_WORDS = re.compile(
    r"\b(portable|portables|laptop|notebook|macbook|ultrabook|chromebook)\b", re.I)
# Mobile chip suffixes (H, HX, HS, U). Never K, F or X, which are desktop.
_MOBILE_CPU = re.compile(
    r"\b(?:i[3579]|ryzen\s*[3579])[\s-]*\d{4,5}\s*(?:hx|hs|h|u)\b", re.I)
# Laptop lines that never say "laptop". Card brands that share a name with a
# laptop line (ROG Strix, TUF, Nitro) only count with the laptop model number.
_LAPTOP_FAMILY = re.compile(
    r"\b(?:legion|victus|omen|katana|zephyrus|vivobook|zenbook|ideapad|thinkpad|yoga"
    r"|loq|alienware|xps|predator|aspire|razer\s*blade|gf63|cyborg|crosshair"
    r"|strix\s*(?:scar|g\s*\d{2})|scar\s*\d{2}|tuf\s*(?:gaming\s*)?[af]\s*\d{2}"
    r"|acer\s*nitro|nitro\s*(?:v|5|\d{2})\b|msi\s*(?:sword|raider|stealth|titan|vector|pulse)"
    r"|dell\s*g\s*1[5-6]|(?:13|14|15|16|17|18)(?:[.,]\d)?\s*(?:\"|”|''|pouces?|inch|duim))",
    re.I)
# Categories a laptop ad can impersonate by naming the chip inside it.
_DESKTOP_PARTS = frozenset({"gpu", "cpu", "motherboard", "ram", "storage"})

_CARRIERS = r"(?:proximus|orange|base|telenet|voo|scarlet|mobile\s*vikings|sfr|bouygues|free)"
# Written however the clerk typed it: "(Uniq. Proximus)", "ONLY-PROXIMUS",
# "(proximus uniquement)", "Bloque Orange". "Simlock" alone is not a lock:
# "simlockvrij", "sans simlock" and "geen simlock" all mean unlocked, so only
# the locked forms count ("simlocke", Dutch "met simlock").
_CARRIER_LOCK = re.compile(
    rf"\b(?:only|uniq\w*|uniquement|enkel|alleen|bloqu\w*|geblokkeerd)[\s.,;:)(-]*{_CARRIERS}\b"
    rf"|\b{_CARRIERS}[\s.,;:)(-]*(?:only|uniq\w*|uniquement|enkel|alleen)\b"
    r"|\bsimlocke\b|\bmet\s+simlock\b|\bbloqu\w*\s+operateur\b")


def aisle_bars_machines(source_category: str | None) -> bool:
    c = (source_category or "").lower()
    return bool(c) and any(w in c for w in _NON_MACHINE_AISLES)


def is_part_aisle(source_category: str | None) -> bool:
    c = (source_category or "").lower()
    return bool(c) and any(w in c for w in _PART_AISLES)


def components_of(l: Listing, catalog: Catalog) -> list[Component]:
    """Recognized parts, minus the machines the shop's aisle rules out."""
    comps = recognize(l.title, l.description, catalog)
    if aisle_bars_machines(l.source_category):
        comps = [c for c in comps if c.category not in MACHINE_CATEGORIES]
    return comps


def is_laptop(text: str, comps: list[Component]) -> bool:
    """A laptop, even when it never says so. Handhelds say "console portable"
    and are consoles, so a recognized console settles it."""
    if any(c.category == "console" for c in comps):
        return False
    return bool(_LAPTOP_WORDS.search(text) or _MOBILE_CPU.search(text))


def names_a_laptop(title: str) -> bool:
    """Stricter, title-only: also catches laptop model lines ("Legion")."""
    return bool(_LAPTOP_WORDS.search(title) or _MOBILE_CPU.search(title)
                or _LAPTOP_FAMILY.search(title))


def teaching_key(l: Listing, catalog: Catalog) -> str | None:
    """The component this ad may set the market price of, or None.

    Only a clean single item teaches: no bundle, no accessory wording, and no
    laptop naming its chip (41 laptops once put the RTX 4070 card at 700 EUR
    against a real 450-500).
    """
    if is_bundle(l.title) or not teaches_price(l.title):
        return None
    pk = primary_key(components_of(l, catalog))
    if pk is None:
        return None
    if catalog.by_key[pk].category in _DESKTOP_PARTS and names_a_laptop(l.title):
        return None
    return pk


def carrier_locked(text: str) -> bool:
    return bool(_CARRIER_LOCK.search(plain(text)))
