"""Phone families split like iPads: one key must not price two phones."""
import pytest

from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


@pytest.mark.parametrize("title, key", [
    ("Samrtphone Honor Magic pro 6 Black 512gb", "honor-magic-old"),
    ("Honor Magic 7 Pro 512 Go", "honor-magic-7"),
    ("Honor Magic 8 pro 512 gb", "honor-magic-8"),
    ("HONOR MAGIC V3 512GB", "honor-magic-v"),
    ("Honor magic v2", "honor-magic-v"),
    ("GSM HONOR MAGIC V5 16ram/512Gb", "honor-magic-v"),
    ("Xiaomi 17 t pro 512 GB avec boite", "xiaomi-17t-pro"),
    ("smartphone xiaomi 17 t pro noir 512", "xiaomi-17t-pro"),
    ("Xiaomi 17T Pro 512Go", "xiaomi-17t-pro"),
    ("Xiaomi 17 Pro max 512 GB 16 GB Ram", "xiaomi-17-pro-max"),
    ("Xiaomi 17 ultra", "xiaomi-17-ultra"),
    ("GSM Xiaomi 17  528 GB avec boite", "xiaomi-17"),
])
def test_each_phone_gets_its_own_price(title, key):
    assert [c.key for c in recognize(title, "", CATALOG)] == [f"phone:{key}"]
