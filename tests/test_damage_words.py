"""Damage and non-items that reached the top of the board on 2026-09-09.

Three of the ten best "deals" were not deals:
  - "Samsung Z Flip 7 / SCHERMPROBLEEM!" (325 EUR): Dutch for screen problem;
  - "Reparation ecran Samsung Galaxy S24 Ultra pas cher Garantie" (260 EUR):
    a repair shop selling a service, not a phone;
  - "GSM Samsung s23 ultra (Probleme app photo)": a broken camera.
"""
import datetime as dt

from techflip.domain import Listing
from techflip.geo import Locator
from techflip.hunt import evaluate
from techflip.pricing.appraise import listing_condition
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def test_screen_problems_in_three_languages_are_broken():
    assert listing_condition(None, "Samsung Z Flip 7 / SCHERMPROBLEEM!") == "broken"
    assert listing_condition(None, "GSM Samsung s23 ultra (Problème app photo)") == "broken"
    assert listing_condition(None, "iPhone 15 écran fissuré") == "broken"
    assert listing_condition(None, "Galaxy S24 scherm gebarsten") == "broken"
    assert listing_condition(None, "iPhone 14 pixel mort en haut") == "broken"


def test_a_locked_or_blacklisted_phone_is_broken():
    """An iCloud lock or a blacklisted IMEI makes the handset unsellable."""
    assert listing_condition(None, "Iphone 16e 128Go (Blacklist réseau)") == "broken"
    assert listing_condition(None, "iPhone 13 bloqué icloud") == "broken"


def test_no_problem_is_not_a_problem():
    """"fonctionne sans problème" is the commonest reassurance on the site."""
    assert listing_condition(None, "iPhone 13 fonctionne sans problème") == "working"
    assert listing_condition(None, "Switch OLED, aucun problème, boite") == "working"
    assert listing_condition(None, "PS5 werkt zonder problemen") == "working"
    assert listing_condition(None, "Galaxy S23 geen probleem") == "working"


def _l(title, price=260):
    return Listing(source="2ememain", source_id=title[:14], url="u", title=title,
                   price=price, published_at=dt.date.today().isoformat(),
                   description="", city="Schaerbeek", lat=50.86, lng=4.37)


def test_a_repair_service_is_not_an_item_for_sale(tmp_path):
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    for t in ("Réparation écran Samsung Galaxy S24 Ultra pas cher Garantie",
              "Reparatie scherm iPhone 15 Pro",
              "Remplacement batterie iPhone 14"):
        assert evaluate(_l(t), CATALOG, tracker, Locator()) is None, t


def test_a_carrier_lock_is_flagged(tmp_path):
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    f = evaluate(_l("GSM (only proximus) Samsung Galaxy Zflip 7 256", 350),
                 CATALOG, tracker, Locator())
    assert f is not None and "locked" in f.flags


def test_a_named_hinge_condition_on_a_folding_phone_is_damage():
    """Cash Converters files a broken fold as "(ETAT CHARNIERE)". Two of them,
    a Z Fold 7 at 550 EUR and a Z Flip 7 at 300, led the 2026-09-17 board at
    +232 and +184. The hinge is the one part of a folding phone that matters."""
    assert listing_condition(
        None, "Smartphone (Sans Garantie) Samsung (ETAT CHARNIÈRE) Z Fold 7") == "broken"
    assert listing_condition(
        None, "Smartphone (sans garantie) Samsung (état Charniere) Z Flip 7") == "broken"


def test_the_shop_names_the_broken_part_in_parentheses():
    """Cash Converters writes the defect as "(etat <part>)": "(ETAT CHARNIERE)
    Z Fold 7", then "(etat lentille) S25 Ultra" at 500 EUR, which led the
    2026-09-20 board. "(Etat) 100 %" is just condition plus battery and must
    stay clean."""
    assert listing_condition(
        None, "(Sans Garantie) Smartphone Samsung S25 Ultra (état lentille)") == "broken"
    assert listing_condition(None, "Smartphone Samsung (etat ecran) Galaxy S24") == "broken"
    assert listing_condition(
        None, "Smartphone Samsung Galaxy S26 (Etat) 100 256 GB Blue") == "working"


def test_sold_as_is_with_a_screen_to_replace_is_broken():
    """"Apple iPhone 14 Pro" at 280 EUR, 19 km away: "le telephone s'allume et
    s'eteint apres 5 minutes, c'est l'ecran qui est a changer, vendu dans
    l'etat"."""
    assert listing_condition(
        None, "le téléphone s'allume et s'éteint après 5 minutes d'utilisation "
              "c'est l'écran qui est a changer vendu dans l'état") == "broken"
    assert listing_condition(None, "vendu en l'état, batterie à changer") == "broken"


def test_any_carrier_lock_counts_not_just_proximus(tmp_path):
    """"Smartphone iphone 16 E blanc 128 Bloque Orange" at 300 EUR scored +83
    at Couillet. Orange, Base, Telenet and VOO lock a handset exactly as
    Proximus does."""
    from techflip.domain import Listing
    from techflip.geo import Locator
    from techflip.hunt import evaluate
    from techflip.pricing.catalog import load_catalog
    from techflip.pricing.tracker import PriceTracker
    from techflip.storage import Store
    cat = load_catalog("config/pricebook.yaml")
    tracker = PriceTracker(Store(tmp_path / "t.db"), cat, 5, 90)
    for t in ("Smartphone iphone 16 E blanc 128 Bloqué Orange",
              "GSM Samsung Galaxy S24 (uniquement Base)",
              "iPhone 15 alleen Telenet"):
        f = evaluate(Listing(source="cashconverters", source_id=t[:12], url="u",
                             title=t, price=300, published_at="2026-09-21",
                             description="", city="Couillet", lat=50.4, lng=4.4),
                     cat, tracker, Locator())
        assert f is not None and "locked" in f.flags, t


def test_an_abbreviated_carrier_lock_still_counts():
    """Cash Converters writes "(Uniq. Proximus)" and "(uniq,proximus)". The
    period and comma sat between the two words and the lock filter missed
    both, so two locked S25 FE ranked at +51 after a markdown."""
    from techflip.hunt import _CARRIER_LOCK
    for t in ("Smartphone Samsung (Uniq. Proximus) S25Fe 128",
              "Smartphone (uniq,proximus) Samsung Galaxy S25 FE",
              "GSM (ONLY-PROXIMUS) Galaxy S24"):
        assert _CARRIER_LOCK.search(t), t
