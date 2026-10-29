"""Traps in the 2026-10-17 refresh, each of which ranked in the top 16.

  "Samsung S25 Ultra" 300 EUR: "Lisez bien l'annonce, c'est une copie."
  "Iphone 16 pro max" 500 EUR: "glas achterkant wel gebroken".
  "honor magic 7 lite" 250 EUR valued as a flagship Magic (735 privately);
      the Lite asks 210.
  "Surface Pro 7 i5" 200 EUR valued at a generation-blind 475; a Pro 7 asks
      300, a Pro 4 or 5 asks 200, only a Pro 9 and later ask 690.
"""
import datetime as dt

from techflip.domain import Listing
from techflip.geo import Locator
from techflip.hunt import evaluate
from techflip.pricing.appraise import listing_condition
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _ev(tmp_path, title, desc="", price=300):
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    return evaluate(Listing(source="2ememain", source_id=title[:14], url="u",
                            title=title, price=price,
                            published_at=dt.date.today().isoformat(),
                            description=desc, city="Bruxelles", lat=50.85, lng=4.35),
                    CATALOG, tracker, Locator())


def _key(title, category):
    return next((c.key for c in recognize(title, "", CATALOG)
                 if c.category == category), None)


def test_a_copy_admitted_in_the_description_is_not_priced(tmp_path):
    assert _ev(tmp_path, "Samsung S25 Ultra",
               "Lisez bien l'annonce, c'est une copie.") is None
    assert _ev(tmp_path, "iPhone 16 Pro", "Dit is een kopie, geen origineel") is None


def test_a_copy_of_the_invoice_is_fine(tmp_path):
    """"copie de la facture" is a reassurance, not an admission."""
    f = _ev(tmp_path, "Samsung Galaxy S25 Ultra 256",
            "Vendu avec copie de la facture et boite")
    assert f is not None


def test_broken_back_glass_in_dutch_is_broken():
    assert listing_condition(
        None, "touch screen goed, glas achterkant wel gebroken") == "broken"


def test_the_lite_is_not_the_flagship():
    assert _key("honor magic 7 lite 256 gb", "phone") == "phone:honor-magic-lite"
    assert _key("Smartphone honor magic 8 lite noir 512gb", "phone") == "phone:honor-magic-lite"
    assert _key("Honor Magic 7 Pro 512Go", "phone") == "phone:honor-magic"


def test_surface_generations_are_separated():
    assert _key("TABLETTES Surface Pro 7 (i5 -11th) 8gb ram 256", "tablet") == "tablet:surface-pro-7"
    assert _key("Surface Pro 4 i5 / 8GB / 256GB with keyboard", "tablet") == "tablet:surface-pro-old"
    assert _key("Microsoft Surface Pro 11 Snapdragon X", "tablet") == "tablet:surface-pro-new"


def test_an_aftermarket_screen_is_flagged():
    """"Apple iPhone 17 Batterie 100 % 256gb (ecran Non Officiel)" at 500 EUR
    scored +136. A non-genuine screen makes iOS show "unknown part" for life
    and buyers knock 150 EUR off; the shop says so in the title."""
    assert listing_condition(None, "Apple iPhone 17 256gb (écran Non Officiel)") == "broken"
    assert listing_condition(None, "iPhone 15 écran pas d'origine") == "broken"
    assert listing_condition(None, "Galaxy S24 scherm niet origineel") == "broken"


def test_carrier_named_before_the_lock_word_is_locked(tmp_path):
    f = _ev(tmp_path, "Smartphone (proximus uniquement) samsung s25fe navy 8gb/128gb", price=200)
    assert f is None or "locked" in f.flags


def test_a_network_switch_is_not_a_nintendo_switch(tmp_path):
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    f = evaluate(Listing(source="2ememain", source_id="mk", url="u",
                         title="mikrotik switch crs125", price=95,
                         published_at=dt.date.today().isoformat(), description="",
                         city="Namur", lat=50.46, lng=4.87,
                         source_category="commutateurs-reseau"),
                 CATALOG, tracker, Locator())
    assert f is None
