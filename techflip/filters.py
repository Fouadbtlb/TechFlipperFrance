"""Cheap prefilters, before any valuation work: price band, hard scam reject,
and ads that are not an offer of the thing they name."""
from __future__ import annotations

import re

from .domain import Listing
from .text import plain


def text_prefilter(l: Listing, require: tuple[str, ...],
                   exclude: tuple[str, ...]) -> tuple[bool, str]:
    """A search's require (ALL must match) / exclude (NONE may match) regexes
    against title+description. This is what drops "recherche"/"achète" want-ads."""
    blob = f"{l.title} {l.description or ''}"
    for rx in exclude:
        if re.search(rx, blob, re.IGNORECASE):
            return False, f"exclu par /{rx}/"
    for rx in require:
        if not re.search(rx, blob, re.IGNORECASE):
            return False, f"manque /{rx}/"
    return True, "ok"


def price_prefilter(l: Listing, min_price: float, max_price: float | None,
                    max_eval_price: float) -> tuple[bool, str]:
    if l.price is None:
        return False, "prix absent"
    if l.price < min_price:
        return False, f"prix {l.price:.0f} < min {min_price:.0f}"
    if max_price is not None and l.price > max_price:
        return False, f"prix {l.price:.0f} > max {max_price:.0f}"
    if l.price > max_eval_price:
        return False, f"prix {l.price:.0f} > plafond {max_eval_price:.0f}"
    marker = scam_marker(l)
    if marker is not None:
        return False, f"signal verrouillage/arnaque: {marker}"
    return True, "ok"


# Listings never worth alerting on whatever the maths say: activation/account
# locks (phone or ex-corp laptop) and box/shell-only sold at product price. These
# are unambiguous phrases; carrier-unlock terms ("desimlocke", "debloque tout
# operateur") are deliberately NOT here since they say nothing about iCloud/FRP.
_SCAM_MARKERS = (
    "bloque icloud", "icloud bloque", "verrouille icloud",
    "verrouillage d activation", "activation lock",
    "compte google oublie", "frp lock",
    "mot de passe bios", "bios verrouille",
    "boite vide", "carton seul", "coque uniquement",
    "vends juste la boite", "juste le carton",
)


def scam_marker(l: Listing) -> str | None:
    blob = plain(f"{l.title} {l.description or ''}")
    for m in _SCAM_MARKERS:
        if m in blob:
            return m
    return None


# Someone looking to BUY. Title only, anchored to the front: deeper in a title
# the same verb is sales copy ("PS5 recherchee par tous").
_WANTED = re.compile(
    r"^\W*(?:(?:je|ik|on|nous)\s+(?:ben\s+)?)?"
    r"(?:recherch\w*|cherch\w*|achet\w*|achat|"
    r"gezocht|zoek\w*|op zoek|gevraagd|wanted|looking for)\b")
# A repair shop advertising its service: "Reparation ecran Samsung Galaxy S24
# Ultra pas cher Garantie" (260 EUR) was priced as a 487 EUR phone.
_SERVICE = re.compile(
    r"^\W*(?:reparation|reparatie|herstelling|remplacement|vervanging|depannage)\b")
# "Moet weg of ruilen tegen iPhone 16": the model named is the one the seller
# WANTS; what they offer is not named at all.
_SWAP = re.compile(r"\bruil\w*\s+tegen\b|\bechang\w*\s+(?:contre|tegen)\b"
                   r"|\bswap\s+(?:for|against)\b")
_COUNTERFEIT = re.compile(r"\b(?:replique|replica|copie|clone|fake|namaak|imitation)\b")
# In a description "copie" alone is usually the invoice ("copie de la
# facture"). Only the admission counts: "c'est une copie".
_ADMITTED_COPY = re.compile(
    r"\b(?:c\W?est|est|is|it\W?s|dit\s+is)\s+(?:une|een|a|an)\s+"
    r"(?:copie|kopie|replica|replique|copy|fake|namaak|imitation|clone)\b")
# No genuine flagship ships from these: "S24 Ultra 512 Go" at 250 EUR said
# "achete sur le site chinois aliexpress".
_CLONE_SHOP = re.compile(r"\b(?:aliexpress|temu|wish\.com|dhgate)\b")


def not_an_offer(l: Listing, comps=()) -> str | None:
    """Why this ad is not an offer of the item it names, or None.

    `comps`: the recognized parts, needed for the clone-shop rule (phones)."""
    title, desc = plain(l.title), plain(l.description)
    if _WANTED.match(title):
        return "annonce de recherche, pas une vente"
    if _SERVICE.match(title):
        return "service de réparation, pas un objet"
    if _SWAP.search(title):
        return "échange, pas une vente"
    if _COUNTERFEIT.search(title) or _ADMITTED_COPY.search(desc):
        return "copie ou contrefaçon"
    if any(c.category == "phone" for c in comps) and _CLONE_SHOP.search(f"{title} {desc}"):
        return "téléphone acheté sur un site de clones"
    return None
