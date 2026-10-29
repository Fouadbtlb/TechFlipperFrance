"""Accessories valued as the device they fit, found topping the app's feed."""
import pytest

from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _devices(title):
    return [c.key for c in recognize(title, "", CATALOG) if c.category in ("phone", "tablet", "console")]


@pytest.mark.parametrize("title", [
    "Samsung Book Cover Keybord Slim voor Galaxy Tab S11 Ultra",
    "Galaxy Tab S11 Book Cover Keyboard Slim AZERTY",
    "Apple Magic Keyboard voor ipad pro 12,9” & ipad",
    "Magic Keyboard Ipad Pro 13”",
    "Étui clavier AZERTY BlueBuilt pour iPad Pro 13 pouces",
    "book cover samsung tab S9+ S9 FE S9 FE+",
    "JBL Flip 7 avec boite",
    "Enceinte BT JBL Flip 7 Tommorowland",
    "hp bluetooth jbl z flip 6 camouflage",
    "Nintendo Switch 2 Joy-Con set Blauw/Rood",
])
def test_an_accessory_is_not_the_device(title):
    assert _devices(title) == []


@pytest.mark.parametrize("title, key", [
    ("iPad Pro 12,9 M1 2021 + Magic Keyboard", "tablet:ipad-pro-m-13"),
    ("Samsung Galaxy Tab S9 avec clavier", "tablet:galaxy-tab-s9"),
    ("Samsung Galaxy Z Flip 7 256gb", "phone:z-flip-7"),
    ("TABLETTES apple ipad pro 2018  13  256 go gris Wifi", "tablet:ipad-pro-old"),
])
def test_the_device_itself_still_counts(title, key):
    assert _devices(title) == [key]


def test_a_plus_model_name_is_not_a_bundle():
    assert _devices("Galaxy Tab S9+/S9FE+/S10+ Book Cover Keyboard | Refurbished") == []


@pytest.mark.parametrize("title, key", [
    ("Honor magic 5 lite", "phone:honor-magic-lite"),
    ("iPad Pro 9.7 (2016) + cover + lader + orginele doos", "tablet:ipad-pro-2017"),
    ("Ipad pro 11 2018", "tablet:ipad-pro-old"),
    ("Microsoft Surface Pro X SQ2 16 Go / 256 Go + Clavier", "tablet:surface-pro-7"),
    ("GSM Xiaomi 15 t pro   512gb  (Etat moyen)", "phone:xiaomi-15t-pro"),
])
def test_more_families_land_on_the_right_model(title, key):
    assert _devices(title) == [key]


def test_a_phone_that_no_longer_turns_on_is_broken():
    from techflip.pricing.appraise import listing_condition
    text = "Samsung Galaxy s24 Ultra 256GB 2 jaar geleden gekocht maar gaat niet meer aan."
    assert listing_condition(None, text, "Samsung Galaxy s24 Ultra 256GB") == "broken"
