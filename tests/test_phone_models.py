"""The phone aisle was 74% unpriceable: 2 469 listings, 697 000 EUR of stock.

Adding the models is only half of it. The variants have to beat their own
parents in the match order, or "Galaxy S25 Edge" is priced as a plain S25 and
"iPhone 16e" as an iPhone 16, which is a 100 EUR error each way.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _phone(title):
    return next((c.key for c in recognize(title, "", CATALOG)
                 if c.category == "phone"), None)


def test_the_new_models_are_recognized():
    assert _phone("GSM Samsung S26 ultra 256 Black") == "phone:s26-ultra"
    assert _phone("GSM Samsung Fold 7 256gb") == "phone:z-fold-7"
    assert _phone("Smartphone Samsung Galaxy Z Flip 7 512") == "phone:z-flip-7"
    assert _phone("Smartphone Apple iPhone SE 64Go") == "phone:iphone-se"
    assert _phone("Xiaomi Redmi Note 13 Pro 256") == "phone:redmi-note-13"
    # Honor was the honest "unknown" here until 2026-09-29, when the private
    # market was measured and it turned out to be the widest shop-to-private
    # gap in the whole phone aisle: 430 against 710.
    assert _phone("GSM HONOR MAGIC V5") == "phone:honor-magic"


def test_a_variant_never_matches_as_its_parent():
    assert _phone("Samsung Galaxy S25 Edge 256Go") == "phone:s25-edge"
    assert _phone("Samsung Galaxy S25 FE") == "phone:s25-fe"
    assert _phone("Samsung Galaxy S25 Ultra 512") == "phone:s25-ultra"
    assert _phone("Samsung Galaxy S24 FE 128") == "phone:s24-fe"
    assert _phone("Samsung Galaxy S22 Ultra") == "phone:s22-ultra"
    assert _phone("Apple iPhone 16e 128Go") == "phone:iphone-16e"
    assert _phone("Xiaomi 15T Pro 512") == "phone:xiaomi-15t-pro"


def test_the_plain_model_still_matches_when_it_is_plain():
    assert _phone("Samsung Galaxy S25 128Go Noir") == "phone:s25"
    assert _phone("Apple iPhone 16 256Go") == "phone:iphone-16"
    assert _phone("Samsung Galaxy S26 256Go") == "phone:s26"


def test_the_fe_variant_is_not_the_full_model():
    """Flip 7 FE asks 450 between private sellers, the Flip 7 asks 650. Pooling
    them made every FE in a shop look like a 200 EUR win."""
    assert _phone("SAMSUNG Galaxy z flip 7 fe 128Go") == "phone:z-flip-7-fe"
    assert _phone("Smartphone Samsung Z Flip 7 512Go") == "phone:z-flip-7"
