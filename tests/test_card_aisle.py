"""A graphics card filed under graphics cards is a card, not a tower.

"Gigabyte GeForce RTX 3080 PC de jeu 10G" (400 EUR) and "PC de jeu Gigabyte
RX 7800 XT 16 Go" (425 EUR) both sat in 2ememain's /cartes-video/ aisle and
both descriptions said card only. The words "PC de jeu" in the title made them
read as whole builds, so they were valued against complete towers (849 EUR for
the 3080) and topped the board at +400.
"""
import datetime as dt

from techflip.domain import Listing
from techflip.geo import Locator
from techflip.hunt import evaluate
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _ev(tmp_path, title, aisle, price=400):
    tracker = PriceTracker(Store(tmp_path / "t.db"), CATALOG, 5, 90)
    return evaluate(Listing(source="2ememain", source_id=title[:14], url="u",
                            title=title, price=price,
                            published_at=dt.date.today().isoformat(),
                            description="", city="Mere", lat=50.9, lng=3.97,
                            source_category=aisle), CATALOG, tracker, Locator())


def test_a_card_in_the_card_aisle_is_valued_as_a_card(tmp_path):
    f = _ev(tmp_path, "Gigabyte GeForce RTX 3080 PC de jeu 10G", "cartes-video")
    assert f is not None and f.kind != "build"
    assert f.value < 600          # a 3080 card, not a 3080 tower


def test_the_same_title_in_the_desktop_aisle_is_still_a_build(tmp_path):
    f = _ev(tmp_path, "PC de jeu RTX 3080 Ryzen 5 5600X 32Go", "ordinateurs-de-bureau", 900)
    assert f is not None and f.kind == "build"
