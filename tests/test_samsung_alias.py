"""Cash Converters writes "Samsung S26", never "Galaxy S26".

79 listings averaging 500 EUR, about 40 000 EUR of stock, were unvaluable
because every Samsung entry in the pricebook is aliased on "galaxy <model>"
and the shops drop that word.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _phone(title):
    return next((c.key for c in recognize(title, "", CATALOG)
                 if c.category == "phone"), None)


def test_samsung_without_galaxy_is_still_the_phone():
    assert _phone("Samsung S26 256gb sans boite") == "phone:s26"
    assert _phone("GSM Samsung S24 128gb") == "phone:s24"
    assert _phone("Smartphone Samsung S23 Ultra 256") == "phone:s23-ultra"
    assert _phone("Samsung S25 FE 128") == "phone:s25-fe"


def test_the_galaxy_form_still_works():
    assert _phone("Samsung Galaxy S26 256GB") == "phone:s26"
    assert _phone("Galaxy S24 Ultra") == "phone:s24-ultra"


def test_the_newest_folding_pair_is_known():
    assert _phone("Samsung Flip 8 256gb") == "phone:z-flip-8"
    assert _phone("Samsung Galaxy Z Fold 8 512") == "phone:z-fold-8"
