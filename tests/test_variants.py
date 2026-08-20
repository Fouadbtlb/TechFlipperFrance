"""A bare title hides the cheaper variant; the description usually names it.

Live case that reached the phone as a +40 EUR deal: title "Ps5", description
"Edition : Digiale". It was valued as the disc console (seed 420) when it is a
Digital (360), so the whole margin was invented.

Refinement only ever moves to a cheaper, more specific sibling, so reading the
description here cannot inflate a listing the way a compatibility list would.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _keys(title, desc=""):
    return [c.key for c in recognize(title, desc, CATALOG)]


def test_digital_ps5_is_not_valued_as_the_disc_model():
    assert _keys("Ps5", "Edition : Digiale, couleur blanche") == ["console:ps5-digital"]
    assert _keys("PS5", "édition numérique") == ["console:ps5-digital"]
    assert _keys("PlayStation 5", "sans lecteur de disque") == ["console:ps5-digital"]


def test_disc_ps5_stays_the_disc_model():
    assert _keys("PS5 edition disque", "avec lecteur") == ["console:ps5"]
    assert _keys("Ps5", "très bon état, avec sa manette") == ["console:ps5"]


def test_switch_variants_are_read_from_the_description():
    assert _keys("Nintendo Switch", "modèle Lite, gris") == ["console:switch-lite"]
    assert _keys("Nintendo Switch", "écran OLED 64go") == ["console:switch-oled"]
    assert _keys("Nintendo Switch", "avec 2 joycons") == ["console:switch"]


def test_refinement_never_upgrades_to_a_dearer_model():
    # "pro" in a description must not turn a plain PS5 into a PS5 Pro: only
    # downward moves are allowed, so an ad bragging about a Pro stays a PS5.
    assert _keys("Ps5", "manette pro incluse, mieux qu'une PS5 Pro") == ["console:ps5"]
