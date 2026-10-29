"""The shop's own aisle is ground truth about what it is selling.

"Edition Collector PlayStation 5 Dragon Ball Sparking Zero" (200 EUR) was
valued as a 340 EUR console. Nothing in the title says "game" -- but Cash
Converters filed it under /jeux-playstation/, and that was being discarded.

Same principle as the LLM `type` guard in `items_from_classification`: when the
source states the kind of thing it is, a machine only counts if the source says
a machine is for sale.
"""
from techflip.domain import Listing
from techflip.geo import Locator
from techflip.hunt import evaluate
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.sources.cashconverters import _category_of
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _ctx(tmp_path):
    store = Store(tmp_path / "t.db")
    return PriceTracker(store, CATALOG, 5, 90), Locator()


def _l(title, cat):
    return Listing(source="cashconverters", source_id=title[:12], url="u",
                   title=title, price=200, published_at="2026-08-20",
                   description="", city="Mons", lat=50.45, lng=3.95,
                   source_category=cat)


def test_the_aisle_is_read_from_the_product_url():
    assert _category_of(
        "https://www.cashconverters.be/fr/jeux-playstation/1216842-edition.html"
    ) == "jeux-playstation"
    assert _category_of(
        "https://www.cashconverters.be/fr/consoles-sony/974054-console-ps4.html"
    ) == "consoles-sony"
    assert _category_of("https://www.cashconverters.be/") is None


def test_a_game_aisle_bars_the_console_it_names(tmp_path):
    tracker, loc = _ctx(tmp_path)
    f = evaluate(_l("Edition Collector PlayStation 5 Dragon Ball Sparking Zero",
                    "jeux-playstation"), CATALOG, tracker, loc)
    assert f is None or not any(p.startswith("PS5") for p in f.parts)


def test_an_accessory_aisle_bars_it_too(tmp_path):
    tracker, loc = _ctx(tmp_path)
    f = evaluate(_l("Carte D'extension Xbox Series S Western Digital 512",
                    "accessoires-jeux-video"), CATALOG, tracker, loc)
    assert f is None or not any("Xbox" in p and "extension" not in p for p in f.parts)


def test_the_console_aisle_keeps_its_console(tmp_path):
    tracker, loc = _ctx(tmp_path)
    f = evaluate(_l("Console PS5 edition disque", "consoles-sony"),
                 CATALOG, tracker, loc)
    assert f is not None and any("PS5" in p for p in f.parts)


def test_a_source_that_states_no_category_is_unaffected(tmp_path):
    tracker, loc = _ctx(tmp_path)
    f = evaluate(_l("Console PS5 edition disque", None), CATALOG, tracker, loc)
    assert f is not None and any("PS5" in p for p in f.parts)
