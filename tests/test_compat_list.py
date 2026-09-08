"""A platform list is compatibility, not contents.

"Logitech G29 + Shifter + Pedalen | PS5/PS4/PC" was valued at 340 EUR as a
PlayStation 5. It is a steering wheel. The accessory guard did not fire because
the "+" reads as a bundle marker -- and the wheel really is a bundle, of wheel
parts.

The tell is the platform run itself: no one sells a console that is also a PS4
and also a PC. Two or more platforms joined by a slash, or trailing the word
"compatible", describe what the accessory plugs into.
"""
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def _consoles(title, desc=""):
    return [c.key for c in recognize(title, desc, CATALOG)
            if c.category == "console"]


def test_a_slash_run_of_platforms_is_not_a_console():
    assert _consoles("Logitech G29 + Shifter + Pedalen | PS5/PS4/PC") == []
    assert _consoles("Logitech G923 + levier de vitesses + support (PS5/PS4/PC)") == []
    assert _consoles("Volant Logitech G29 PS5/PC") == []
    assert _consoles("Manette PS4/PS5 Nacon Revolution Pro Controler 2") == []


def test_the_word_compatible_says_the_same_thing():
    assert _consoles("Volant logitech g29 + support vevor",
                     "Pédalier X3. Compatible PS4 - PS5") == []


def test_one_platform_alone_is_still_the_console_for_sale():
    assert _consoles("Console PS5 edition disque")
    assert _consoles("Ps5")
    assert _consoles("PS5 Pro 30th Anniversary Édition Limitée – Numérotée")


def test_a_real_two_console_lot_survives_the_rule():
    """"PS4 + PS5" joined by a plus is a lot of machines, not a compat list.
    Only one console is ever priced (see `_TITLE_ONLY`), but it must be one."""
    assert _consoles("Vends PS4 + PS5 avec manettes")


def test_a_compat_list_in_the_description_alone_was_never_the_problem():
    """The console only ever comes from the title, so "Compatible PS4 - PS5"
    buried in a wheel's description cannot inflate it. Pinned, not assumed."""
    assert _consoles("Volant logitech g29 + support vevor + volant F1",
                     "Pedalier X3. Compatible PS4 - PS5") == []


def test_the_separator_can_be_a_comma_a_dash_or_an_ampersand():
    """Real titles from the pool. Every one of these was priced as a PS5."""
    assert _consoles("Logitech g29 racestuur + pedalen + shifter (PS4 - PS5 - PC)") == []
    assert _consoles("Logitech G29 Racing Wheel (stuur + pedalen) PS5, PS4 & PC") == []
    assert _consoles("G29 rij stuur en pedalen ps5, ps4, ps3, pc") == []


def test_two_platforms_side_by_side_need_no_separator_at_all():
    assert _consoles("PS4 PS5 stuur") == []


def test_nintendo_switch_is_one_console_not_two_platforms():
    """"nintendo" must stay out of the platform alternation, or the most
    common console name in the pool reads as a compatibility list."""
    assert _consoles("Nintendo Switch")
    assert _consoles("Console Nintendo Switch V1")


def test_xbox_series_x_s_survives_its_own_slash():
    assert _consoles("Console Xbox Series X/S 1To")


def test_a_wheel_is_an_accessory_even_with_one_platform():
    assert _consoles("Nintendo switch stuur") == []
    assert _consoles("HORI Mario Kart Racing Wheel Pro Mini - Nintendo Switch") == []


def test_a_console_named_after_collector_is_the_game_not_the_machine():
    """"Assassin's Creed Shadows Édition Collector PS5" was priced at 340 EUR
    as a console. Word order settles it: the machine comes first when the
    machine is what is for sale."""
    assert _consoles("Assassin's Creed Shadows Édition Collector PS5") == []
    assert _consoles("Edition Collector PlayStation 5 Dragon Ball: Sparking! Zero") == []
    assert _consoles("Ps5 ghost of yotei edition collector")          # a real console
    assert _consoles("CONSOLE PLAYSTATION 4 EDITION COLLECTOR STAR WARS")


def test_a_faceplate_is_not_the_console_it_clips_onto():
    assert _consoles("Ghost of Yotei Façades PS5 Slim Collector Neuf") == []
