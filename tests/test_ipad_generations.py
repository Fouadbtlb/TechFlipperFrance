"""iPads are priced per generation, never as one family.

One "iPad Pro" key priced a 2018 Pro like a 2022 one (850 EUR over 106 ads of
every generation), so iPads filled the top of the app's reliable feed. When the
ad shows no sign of the generation, the cheapest bucket wins.
"""
import pytest

from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


@pytest.mark.parametrize("title, key", [
    ("tablette apple ipad pro 5 (2021) 12,9 128gb silver Wifi", "ipad-pro-m-13"),
    ("iPad Pro (5de generatie) 12,9 inch met 512GB", "ipad-pro-m-13"),
    ("iPad Pro 13-inch m5 Wi-Fi", "ipad-pro-m-13"),
    ("iPad Pro M1 11 pouces (3e gen) gris", "ipad-pro-m-11"),
    ("Ipad Pro M5 11” 256gb", "ipad-pro-m-11"),
    ("iPad Pro 11\" 2020 – 128 Go", "ipad-pro-old"),
    ("Apple Ipad Pro 12,9 inch (4e generatie) 512GB", "ipad-pro-old"),
    # No sign of the generation: the cheapest bucket, the 2015-2017 Pros.
    ("iPad Pro", "ipad-pro-2017"),
    ("iPad Pro 12,9 256Go", "ipad-pro-2017"),
    ("iPad Pro 1ère génération 12,9", "ipad-pro-2017"),
    ("iPad Pro 12.9 Touch ID", "ipad-pro-2017"),
    ("iPad Pro 12,9 avec câble USB-C vers Lightning", "ipad-pro-2017"),
    # Only a 2018-2020 Pro has these.
    ("iPad Pro 11 pouces 128 Go", "ipad-pro-old"),
    ("iPad Pro 12.9 3e génération 64Go", "ipad-pro-old"),
    ("Apple iPad Pro 11\" Face ID 256Go", "ipad-pro-old"),
    ("iPad Pro 12,9 USB-C 256 Go", "ipad-pro-old"),
    ("iPad Pro avec Apple Pencil 2", "ipad-pro-old"),
    ("iPad Pro A12X 64Go", "ipad-pro-old"),
    ("APPLE IPAD AIR 2026 11 INCH M4 NIEUWSTAAT", "ipad-air-m"),
    ("Apple Ipad Air a2588 5th gen 64gb", "ipad-air-m"),
    ("iPad Air 4 (2020) 256GB", "ipad-air-4"),
    ("TABLETTE Apple Ipad Air 3i Gen 10,5 256", "ipad-air-old"),
    ("Apple iPad mini 6 64Go", "ipad-mini-6"),
    ("iPad mini 5 avec coque", "ipad-mini-5"),
    ("iPad Mini 4 64GB", "ipad-mini-old"),
    ("iPad 10e génération 64Go", "ipad-10"),
    ("TABLETTE Apple Ipad 9th gen 64", "ipad-9"),
    ("tablette apple ipad 9 (2021) 64Gb silver", "ipad-9"),
    ("Apple iPad 9.7\" WiFi 32GB (2018, 6th gen)", "ipad-old"),
    ("Ipad 8th gen 128gb Wifi", "ipad-old"),
    ("IPAD APPLE A2270 32 GB", "ipad-old"),
])
def test_each_ipad_lands_in_its_generation(title, key):
    assert [c.key for c in recognize(title, "", CATALOG)] == [f"tablet:{key}"]
