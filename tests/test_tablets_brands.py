"""Tablets and the less common phone brands: 127 000 EUR of stock the pricebook
could not value at all, and the place the chains misprice hardest.

A clerk grades an iPhone confidently and an Honor Magic or a Surface Pro by
guess, so the shop asks 220 for a Surface Pro that private sellers list at 475.
Seeds below are private medians measured on 2026-09-29, sample size on each
line.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _key(title, category):
    return next((c.key for c in recognize(title, "", CATALOG)
                 if c.category == category), None)


def test_tablets_are_recognized():
    assert _key("Tablette Apple iPad Pro M4 13 pouces 256 Go", "tablet") == "tablet:ipad-pro-m-13"
    assert _key("Apple iPad Air 5 64Go wifi", "tablet") == "tablet:ipad-air-m"
    # Split by generation on 2026-10-17: a Pro 8 asks about 300, not 475.
    assert _key("Microsoft Surface Pro 8 i5 256", "tablet") == "tablet:surface-pro-7"
    assert _key("Samsung Galaxy Tab S10 Ultra 256", "tablet") == "tablet:galaxy-tab-s10"


def test_a_variant_beats_the_generic_ipad():
    assert _key("iPad Pro 11 512Go", "tablet") == "tablet:ipad-pro-old"  # no generation named: cheapest
    assert _key("iPad mini 6 64 Go", "tablet") == "tablet:ipad-mini-6"
    assert _key("Apple iPad 9th gen 64Go", "tablet") == "tablet:ipad-9"


def test_the_other_phone_brands_are_recognized():
    assert _key("GSM HONOR MAGIC V5 16ram/512Gb", "phone") == "phone:honor-magic-v"
    assert _key("OnePlus 13 256GB", "phone") == "phone:oneplus-13"
    assert _key("Nothing Phone 2a 256", "phone") == "phone:nothing-phone"


def test_an_ipad_case_is_not_an_ipad():
    """The accessory guard must cover the new category too."""
    assert _key("Coque iPad Pro 11 avec clavier", "tablet") is None
    assert _key("Housse Samsung Galaxy Tab S10", "tablet") is None


def test_the_tab_s11_ultra_is_not_the_tab_s11():
    from techflip.pricing.extract import recognize as _rec
    assert [c.key for c in _rec("Samsung Galaxy Tab S11 Ultra 256 Go", "", CATALOG)] == ["tablet:galaxy-tab-s11-ultra"]
    assert [c.key for c in _rec("TABLETTES Samsung tab S11 128GB", "", CATALOG)] == ["tablet:galaxy-tab-s11"]
