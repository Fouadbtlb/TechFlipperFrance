"""A phone case is not a phone.

"Coque Iphone 14 Pro Max Titane" at 200 EUR was appraised at 408 EUR as the
handset. The console category has had a subject guard since the PSVR2 was
priced as a PS5; the phone category never got one, so every accessory in the
GSM aisle was worth the phone it protects.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _phone(title, desc=""):
    return next((c.key for c in recognize(title, desc, CATALOG)
                 if c.category == "phone"), None)


def test_an_accessory_named_first_is_not_the_phone():
    assert _phone("Coque Iphone 14 Pro Max Titane") is None
    assert _phone("Housse Samsung Galaxy S24 Ultra cuir") is None
    assert _phone("Chargeur rapide pour iPhone 15 Pro") is None
    assert _phone("Protection ecran Galaxy S23 Ultra") is None


def test_the_phone_named_first_keeps_its_extras():
    assert _phone("iPhone 13 128Go avec coque et chargeur") == "phone:iphone-13"
    assert _phone("Samsung Galaxy S24 Ultra + housse") == "phone:s24-ultra"


def test_battery_percentage_is_not_an_accessory():
    """Every Cash Converters phone title carries "Batterie 98 %"."""
    assert _phone("Smartphone Apple iPhone 17 Pro Batterie 98 % 512Go") == "phone:iphone-17-pro"
    assert _phone("GSM Samsung S26 ultra Batterie 100 % 256 Black") == "phone:s26-ultra"


def test_only_one_phone_is_ever_priced():
    """A compatibility list in a description must not add a second handset."""
    got = [c.key for c in recognize("Coque silicone", "compatible iPhone 15, 15 Pro, 14", CATALOG)
           if c.category == "phone"]
    assert got == []
