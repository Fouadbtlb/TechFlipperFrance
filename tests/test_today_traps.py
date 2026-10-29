"""Traps in the 2026-09-14 refresh, each of which ranked in the top 25.

  #1  "Galaxy s26 ultra(replique)"  400 EUR, valued 808: a counterfeit.
  #2  "GSM Samsung Z flip 7 noir 256 coup, pixel droit": a dent and a bad pixel.
  #6  "GSM LIGNE ECRAN!!! samsung z flip 6": a line across the display.
  #21 "Samsung Z Flip 7 256Gb avec boite (Leger coup ecran)": a hit screen.
  #23 "je cherche samsung s26 ou s25 edge": someone wanting to BUY one.
      "Samsung Galaxy S26 256GB" filed under /housses-coques-facades-samsung/.
"""
import datetime as dt

from techflip.domain import Listing
from techflip.geo import Locator
from techflip.hunt import evaluate
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _ev(tmp_path, title, price=300, aisle=None):
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    l = Listing(source="2ememain", source_id=title[:14], url="u", title=title,
                price=price, published_at=dt.date.today().isoformat(),
                description="", city="Mons", lat=50.45, lng=3.95,
                source_category=aisle)
    return evaluate(l, CATALOG, tracker, Locator())


def test_a_counterfeit_is_not_priced_at_all(tmp_path):
    for t in ("Galaxy s26 ultra(réplique)", "iPhone 16 Pro Max replica",
              "Samsung S24 Ultra copie", "iPhone 15 namaak", "Galaxy S25 clone"):
        assert _ev(tmp_path, t) is None, t


def test_screen_damage_written_the_shop_way_is_broken(tmp_path):
    for t in ("GSM Samsung Z flip 7 noir 256 coup, pixel droit",
              "GSM LIGNE ÉCRAN!!! samsung  z flip 6  bleu  256 gb",
              "Samsung Z Flip 7 256Gb avec boite (Leger coup écran)"):
        f = _ev(tmp_path, t)
        assert f is None or "broken" in f.flags, t


def test_a_google_pixel_is_a_brand_not_a_dead_pixel(tmp_path):
    f = _ev(tmp_path, "Smartphone Google Pixel 10 Gris 128 gb", 350)
    assert f is not None and "broken" not in f.flags


def test_a_wanted_ad_in_first_person_is_not_for_sale(tmp_path):
    for t in ("je cherche samsung s26 ou s25 edge", "Je recherche iPhone 15 Pro",
              "Ik zoek een Galaxy S24"):
        assert _ev(tmp_path, t) is None, t


def test_a_phone_filed_under_cases_is_a_case(tmp_path):
    f = _ev(tmp_path, "Samsung Galaxy S26 256GB", 400,
            aisle="telephonie-mobile-housses-coques-facades-samsung")
    assert f is None or not any("Galaxy" in p for p in f.parts)


def test_a_phone_in_the_phone_aisle_survives(tmp_path):
    f = _ev(tmp_path, "Samsung Galaxy S26 256GB", 400,
            aisle="telephonie-mobile-samsung")
    assert f is not None and any("Galaxy" in p for p in f.parts)


def test_dutch_dead_screen_phrases_are_broken():
    """"Iphone 17 pro max ... scherm start niet op dus moet gemaakt worden"
    (800 EUR) ranked 17th: the screen does not turn on."""
    from techflip.pricing.appraise import listing_condition
    assert listing_condition(None, "scherm start niet op dus moet gemaakt worden") == "broken"
    assert listing_condition(None, "gsm werkt niet meer") == "broken"
    assert listing_condition(None, "petit point vert sur l écran") == "broken"


def test_a_phone_bought_on_aliexpress_is_a_clone(tmp_path):
    """"Samsung S24 Ultra 512 Go" at 250 EUR: "achete sur le site chinois
    aliexpress pour 733". No genuine S24 Ultra ships from AliExpress."""
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    l = Listing(source="2ememain", source_id="ali", url="u",
                title="Samsung S24 Ultra 512 Go", price=250,
                published_at=dt.date.today().isoformat(),
                description="acheté sur le site chinois aliexpress pour 733€",
                city="Lummen", lat=51.0, lng=5.2)
    assert evaluate(l, CATALOG, tracker, Locator()) is None


def test_a_swap_request_does_not_name_the_item_for_sale(tmp_path):
    """"Moet weg of ruilen tegen iPhone 16 of 17" (350 EUR) was priced as an
    iPhone 16. The seller WANTS an iPhone 16; what they are selling is not
    named anywhere in the ad."""
    assert _ev(tmp_path, "Moet weg  of ruilen tegen iPhone 16 of 17", 350) is None
    assert _ev(tmp_path, "Galaxy S23 à échanger contre iPhone 15", 350) is None


def test_a_phone_sold_as_parts_is_broken(tmp_path):
    """"Samsung S23 Ultra vendu sans la carte mere (carte mere HS)": a short
    circuit killed the board and the seller is parting it out."""
    f = _ev(tmp_path, "Samsung S23 Ultra vendu sans la carte mère (carte mère HS)", 275)
    assert f is None or "broken" in f.flags
