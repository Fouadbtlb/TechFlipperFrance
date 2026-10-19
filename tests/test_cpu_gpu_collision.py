"""A model number after "Ryzen" is a CPU, whatever card shares the digits.

"PC Gaming Zalman ryzen 5 5600xt rtx 4060 16 GB 500go" (700 EUR, Mouscron):
the shop mistyped the 5600X, the extractor read "5600 xt" as a Radeon RX
5600 XT, and because only one GPU is ever kept it then discarded the real
RTX 4060. The machine was valued at 468 instead of roughly 680.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _gpus(title):
    return [c.key for c in recognize(title, "", CATALOG) if c.category == "gpu"]


def test_a_number_after_ryzen_is_not_a_radeon():
    assert _gpus("PC Gaming Zalman ryzen 5 5600xt rtx 4060 16 GB 500go") == ["gpu:rtx-4060"]
    assert _gpus("Ryzen 5 5600 XT") == []


def test_a_real_radeon_still_matches():
    assert _gpus("Carte graphique RX 5600 XT 6Go") == ["gpu:rx-5600-xt"]
    assert _gpus("PC gamer Ryzen 5 3600 + RX 5600 XT") == ["gpu:rx-5600-xt"]


def test_intel_model_numbers_do_not_become_cards_either():
    assert _gpus("PC core i5 4060 tour") == []
    assert _gpus("PC i5-12400F RTX 4060") == ["gpu:rtx-4060"]
