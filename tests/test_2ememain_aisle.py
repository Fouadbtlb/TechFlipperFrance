"""2ememain states the aisle in its own URL, and it was being thrown away.

94 rows sat under /jeux-sony-playstation-5/ and every one of them was priced as
a 340 EUR PlayStation 5: "Final Fantasy XVI - PS5" at 13 EUR, "Hogwarts Legacy
PS5" at 20. Cash Converters had exactly this bug and it was fixed there by
reading the aisle out of the product URL; the same rule applies here.
"""
from techflip.hunt import _aisle_bars_machines
from techflip.sources.deuxememain import _aisle_of


def test_the_aisle_is_the_second_path_segment():
    assert _aisle_of(
        "https://www.2ememain.be/v/consoles-de-jeu-jeux-video/"
        "jeux-sony-playstation-5/m2432528193-ps5-2k25") == "jeux-sony-playstation-5"
    assert _aisle_of(
        "https://www.2ememain.be/v/informatique-logiciels/"
        "ordinateurs-de-bureau/m2429577584-pc-de-jeu") == "ordinateurs-de-bureau"
    assert _aisle_of("https://www.2ememain.be/") is None


def test_a_game_aisle_bars_the_console_it_names():
    assert _aisle_bars_machines("jeux-sony-playstation-5")
    assert _aisle_bars_machines("jeux-nintendo-switch")
    assert _aisle_bars_machines("consoles-de-jeu-sony-consoles-accessoires")


def test_a_console_aisle_does_not():
    """"consoles-de-jeu-..." carries the singular "jeu", never "jeux"; the
    guard matches on the plural, and that is what keeps these alive."""
    assert not _aisle_bars_machines("consoles-de-jeu-sony-playstation-5")
    assert not _aisle_bars_machines("consoles-de-jeu-nintendo-switch")
    assert not _aisle_bars_machines("consoles-de-jeu-xbox-series-x-s")
    assert not _aisle_bars_machines("ordinateurs-de-bureau")
