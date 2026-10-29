"""Cash Converters drops words from the title that its own URL keeps.

"Smartphone Samsung z flip 7 black 8gb/128gb" sits at
/gsm/1121635-smartphone-samsung-z-flip-7-FE-black-8gb-128gb.html. The FE asks
450 EUR between private sellers, the real Flip 7 asks 650, so reading the title
alone invented 200 EUR of margin on every FE in the chain.

The slug is the shop's own product name before a clerk retyped it. Same
principle as the aisle: when the source states something, use it.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize
from techflip.sources.cashconverters import _slug_words

CATALOG = load_catalog("config/pricebook.yaml")


def test_the_slug_is_read_back_into_words():
    assert _slug_words(
        "https://www.cashconverters.be/fr/gsm/1121635-smartphone-samsung-z-flip-7-fe-black-8gb-128gb.html"
    ) == "smartphone samsung z flip 7 fe black 8gb 128gb"
    assert _slug_words("https://www.cashconverters.be/") == ""


def test_the_slug_recovers_the_variant_the_title_dropped():
    from techflip.sources.cashconverters import _title
    t = _title({"name": "Smartphone Samsung z flip 7 black  8gb/128gb",
                "url": "https://www.cashconverters.be/fr/gsm/"
                       "1121635-smartphone-samsung-z-flip-7-fe-black-8gb-128gb.html"})
    got = [c.key for c in recognize(t, "", CATALOG) if c.category == "phone"]
    assert got == ["phone:z-flip-7-fe"]


def test_a_title_that_already_says_it_is_unchanged():
    title = "SMARTPHONE Samsung Z flip 7 Fe 128 gb noir"
    got = [c.key for c in recognize(title, "", CATALOG) if c.category == "phone"]
    assert got == ["phone:z-flip-7-fe"]


def test_a_reused_product_page_contributes_nothing():
    """Cash Converters recycles ids: /1211064-pc-gaming-ryzen-5-4th-rtx-4060-...
    now holds "carte graphique Gigabyte RTX 4060 8Gb ddr6". Appending that slug
    turned a 250 EUR card into a 638 EUR tower."""
    from techflip.sources.cashconverters import _variant_hint
    assert _variant_hint("carte graphique Gigabyte RTX 4060 8Gb ddr6",
                         "pc gaming ryzen 5 4th rtx 4060 32 gb 1to ssd") == ""


def test_only_variant_words_are_borrowed():
    from techflip.sources.cashconverters import _variant_hint
    assert _variant_hint("Smartphone Samsung z flip 7 black 8gb/128gb",
                         "smartphone samsung z flip 7 fe black 8gb 128gb") \
        == "smartphone samsung z flip 7 fe black 8gb 128gb"
    # Nothing to add when the title already says it.
    assert _variant_hint("SMARTPHONE Samsung Z flip 7 Fe 128 gb noir",
                         "smartphone samsung z flip 7 fe 128 gb noir") == ""
