"""Two false positives that were delivered to the phone on 2026-08-12.

Both invented a console that was never for sale, which is the failure mode that
costs a wasted drive and destroys trust in every other alert.
"""
from techflip.pricing.appraise import items_from_classification
from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import recognize

CATALOG = load_catalog("config/pricebook.yaml")


def test_a_vr_headset_is_not_a_ps5_with_two_pads():
    """Verbatim verdict for a 260 EUR PSVR2 ad: the model typed it "accessory"
    yet listed a console and two DualSense from the marketing image, valuing a
    headset at 444 EUR. Its own type field is the ground truth to honour."""
    verdict = {
        "type": "accessory",
        "condition": "working",
        "components": [
            {"type": "console", "model": "PS5", "qty": 1},
            {"type": "controller", "model": "DualSense", "qty": 2},
        ],
    }
    items = items_from_classification(verdict, CATALOG)
    assert not [i for i in items if i.category == "console"]
    assert [i.category for i in items] == ["controller"]


def test_a_game_is_not_the_console_printed_on_its_box():
    """Verbatim verdict for "Tekken 8 - Collector's Edition - Xbox", 139 EUR,
    delivered as a +263 EUR deal 34km from Lille on 2026-08-13. Text
    recognition read the ad correctly (nothing at all), so only the LLM spoke,
    and it typed the ad "game" while listing the console off the box art. It
    priced the thing itself at 50 EUR in the same breath.

    Same shape as the PSVR2, and the guard for that one existed -- it just only
    covered "accessory". The rule wanted is the general one: a machine counts
    only when the ad is selling a machine, whatever the non-machine happens
    to be this time.
    """
    verdict = {
        "type": "game",
        "condition": "working",
        "components": [{"type": "console", "model": "Xbox Series X", "qty": 1}],
        "valeur_revente_rapide": 50,
    }
    assert items_from_classification(verdict, CATALOG) == []


def test_every_non_machine_type_bars_a_machine_component():
    for t in ("game", "accessory", "controller", "monitor", "gpu", "phone"):
        verdict = {"type": t, "condition": "working",
                   "components": [{"type": "console", "model": "PS5", "qty": 1}]}
        assert not [i for i in items_from_classification(verdict, CATALOG)
                    if i.category == "console"], t


def test_a_machine_ad_keeps_its_machine():
    """"other" and a missing type stay permissive: they are "I don't know",
    not "this is not a machine", and closing on a shrug would silence real ads."""
    for t in ("console", "pc", "laptop", "other", None):
        verdict = {"type": t, "condition": "working",
                   "components": [{"type": "console", "model": "PS5", "qty": 1}]}
        assert [i.key for i in items_from_classification(verdict, CATALOG)] == ["console:ps5"], t


def test_a_real_console_ad_still_values_its_console():
    verdict = {
        "type": "console",
        "condition": "working",
        "components": [{"type": "console", "model": "PS5", "qty": 1}],
    }
    assert [i.key for i in items_from_classification(verdict, CATALOG)] == ["console:ps5"]


def test_english_word_order_pads_are_not_consoles():
    """Verbatim from the board, 260 EUR appraised as a 368 EUR PS5: "2 Ps5 30th
    Anniversary Limited Edition controllers". The positional rule that catches
    "manette PS5" cannot catch this, because English and Dutch put the console
    name FIRST and still sell an accessory. Position is not enough; the noun
    itself has to count.
    """
    for title in [
        "2 Ps5 30th Anniversary Limited Edition controllers",
        "Ps5 controllers",
        "Nintendo Switch spellen",
        "Xbox Series X controller",
        "PS5 hoes",
    ]:
        assert not [c for c in recognize(title, "", CATALOG) if c.category == "console"], title


def test_a_console_sold_with_its_extras_is_still_a_console():
    """The counter-case, also verbatim: an accessory noun appears, but the ad
    plainly sells the machine and says so."""
    for title in [
        "PS5 disc editie console 825GB + controller, 5 games, kabels",
        "Ps5 avec une manette",
        "Xbox Series X + 2 controllers",
        "Nintendo Switch console met spellen",
    ]:
        assert [c for c in recognize(title, "", CATALOG) if c.category == "console"], title


def test_ps5_portable_is_the_portal_not_a_ps5():
    """'Vend ps5 portable avec coque et pochette 250 euros' is a PlayStation
    Portal (~170), and was valued as a 420 EUR console."""
    keys = [c.key for c in recognize(
        "Ps5", "Vend ps5 portable avec coque et protection pochette 250 euros", CATALOG)]
    assert keys == ["console:ps-portal"]


def test_a_plain_ps5_is_untouched_by_the_portable_rule():
    keys = [c.key for c in recognize(
        "Ps5", "console de salon, tres bon etat, avec sa manette", CATALOG)]
    assert keys == ["console:ps5"]


def test_storage_sold_for_a_console_is_not_the_console():
    """"SSD ps5 2TO", 300 EUR in Lille, was appraised as a 368 EUR PS5. It is a
    drive. Same shape as the pads: the console name comes first and still is not
    what is for sale."""
    for title in ["SSD ps5 2TO", "SSD nvme pour PS5 1To", "Disque dur externe PS4"]:
        assert not [c for c in recognize(title, "", CATALOG)
                    if c.category == "console"], title


def test_a_console_sold_with_a_drive_keeps_its_console():
    for title in ["PS5 avec SSD 2To", "Xbox Series X + SSD 1To"]:
        assert [c for c in recognize(title, "", CATALOG)
                if c.category == "console"], title


def test_a_vr_headset_named_beside_a_console_is_not_the_console():
    """"ps vr 2 ps5", 250 EUR at Cash Converters Mouscron, appraised as a
    340 EUR PS5. A headset is an accessory however the shop titles it."""
    for title in ["ps vr 2 ps5", "PSVR 2 pour PS5", "Casque VR PS4"]:
        assert not [c for c in recognize(title, "", CATALOG)
                    if c.category == "console"], title


def test_only_the_accessory_means_only_the_accessory():
    """Cash Converters writes the shortfall in the title: "Console NINTENDO
    Switch Chargeur Uniquement" is a charger, priced at 120 EUR and valued as a
    161 EUR console. The word "console" made it look like a bundle, so the
    accessory rule stood down -- but "uniquement" says the opposite."""
    for title in [
        "Console NINTENDO Switch Chargeur Uniquement",
        "Console NINTENDO Switch (Joycon Gauche exterieur uniquement)",
        "Console PS4 manette seule",
    ]:
        assert not [c for c in recognize(title, "", CATALOG)
                    if c.category == "console"], title


def test_a_complete_console_with_extras_is_unaffected():
    for title in ["Console NINTENDO SWITCH Neon (etat) + Accessoires",
                  "Console Playstation 4 pro 1to + manette"]:
        assert [c for c in recognize(title, "", CATALOG)
                if c.category == "console"], title


def test_a_second_generation_switch_is_not_a_switch_2():
    """Cash Converters Ath, 200 EUR, titled "Console NINTENDO Switch 2 th gen".
    That is the 2nd-generation (v2) Switch, worth ~160, not the Switch 2 console
    at 355. Three of them were sitting in the shortlist at +150 each."""
    for title in ["Console NINTENDO Switch 2 th gen", "Console NINTENDO switch 2 gen",
                  "Nintendo Switch 2eme generation"]:
        keys = [c.key for c in recognize(title, "", CATALOG) if c.category == "console"]
        assert keys == ["console:switch"], f"{title} -> {keys}"


def test_a_real_switch_2_is_still_a_switch_2():
    keys = [c.key for c in recognize("Console Nintendo Switch 2", "", CATALOG)
            if c.category == "console"]
    assert keys == ["console:switch-2"]


def test_a_case_for_a_handheld_is_not_the_handheld():
    """"Coque Steam Deck OLED 512 Go +, neuve, avec garantie", 370 EUR, valued
    as a 534 EUR Steam Deck. The accessory rule never fired because "deck" was
    not in the console vocabulary at all."""
    for title in ["Coque Steam Deck OLED 512 Go, neuve, avec garantie",
                  "Housse pour Steam Deck", "Chargeur ROG Ally"]:
        assert not [c for c in recognize(title, "", CATALOG)
                    if c.category == "console"], title


def test_a_real_handheld_is_untouched():
    for title in ["Valve Steam Deck OLED 512 Go", "Steam Deck LCD 64go"]:
        assert [c for c in recognize(title, "", CATALOG)
                if c.category == "console"], title


def test_an_elgato_stream_deck_is_not_a_valve_steam_deck():
    """"Steam deck + neuf! Elgato", 160 EUR, valued at 276 as a Valve handheld.
    It is an Elgato Stream Deck, a macro pad."""
    assert not [c for c in recognize("Steam deck + neuf! Elgato", "", CATALOG)
                if c.category == "console"]


def test_a_network_switch_is_not_a_nintendo_switch():
    """Cash Converters stocks both. "Switch ethernet Sodola" (80 EUR) and
    "SWITCH 2,5 TP LINK SG105" (20 EUR) were valued as consoles."""
    for title in ["Switch ethernet Sodola", "SWITCH 2,5 TP LINK SG105",
                  "Switch reseau Netgear 8 ports"]:
        assert not [c for c in recognize(title, "", CATALOG)
                    if c.category == "console"], title


def test_a_real_switch_console_survives_both_guards():
    for title in ["Console NINTENDO Switch Sans Accessoires",
                  "Valve Steam Deck OLED 512 Go"]:
        assert [c for c in recognize(title, "", CATALOG)
                if c.category == "console"], title


def test_a_screen_for_a_console_is_not_the_console():
    """"ECRAN PS5 FAT 4K 60HZ G-STORY" (160 EUR) is a portable monitor, valued
    as a 340 EUR PS5. "ECRAN DE SWITCH NINTENDO SANS JOY-CON" (100) is a spare
    screen, valued as a 166 EUR console."""
    for title in ["ECRAN PS5 FAT 4K 60HZ G-STORY",
                  "ECRAN DE SWITCH  NINTENDO  SANS JOY-CON/ACC",
                  "Moniteur pour PS5", "Scherm voor Nintendo Switch"]:
        assert not [c for c in recognize(title, "", CATALOG)
                    if c.category == "console"], title
