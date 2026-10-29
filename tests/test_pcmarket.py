"""A working PC sells as a machine, not as a bag of parts.

Every PC near Lille scored negative: -64, -107, -143. That is not a market with
no bargains, it is a model valuing a tower at part-out while the tower sells
assembled. Measured over 284 stored towers, an RTX 3060 machine asks a median
of 700 EUR where the parts sum to roughly 400.
"""
from techflip.pcmarket import PC_REALIZATION, PCMarket
from techflip.pricing.catalog import load_catalog

CATALOG = load_catalog("config/pricebook.yaml")


def _market(*rows, min_comparables=5):
    m = PCMarket(min_comparables)
    for i, (title, price) in enumerate(rows):
        m.add(title, "", price, f"2ememain:{i}", CATALOG)
    return m


def test_a_tower_is_priced_against_other_towers():
    m = _market(*[(f"Gaming PC RTX 3060 i5-12400F {i}", p) for i, p in
                  enumerate((650, 700, 700, 750, 800, 690))])
    med, n = m.median_ask("gpu:rtx-3060", cpu="i5")
    assert med == 700 and n == 6
    value, _ = m.whole_value("gpu:rtx-3060", cpu="i5")
    assert value == round(700 * PC_REALIZATION, 2)


def test_thin_evidence_yields_no_opinion():
    """Under the threshold it must say nothing rather than guess from three ads;
    the caller then falls back to the part sum."""
    m = _market(("Gaming PC RTX 4090", 2000), ("Gaming PC RTX 4090", 2500))
    assert m.median_ask("gpu:rtx-4090") == (None, 2)


def test_a_listing_does_not_help_justify_its_own_bargain():
    rows = [(f"Gaming PC RTX 3060 i5-12400F {i}", p) for i, p in
            enumerate((700, 700, 700, 700, 700))]
    m = _market(*rows, ("Gaming PC RTX 3060 i5-12400F cheap", 300))
    med_all, _ = m.median_ask("gpu:rtx-3060", cpu="i5")
    med_self, _ = m.median_ask("gpu:rtx-3060", cpu="i5", exclude_uid="2ememain:5")
    assert med_all == 700 and med_self == 700
    # and the cheap one is not in its own comparable set
    assert m.median_ask("gpu:rtx-3060", cpu="i5", exclude_uid="2ememain:0")[1] == 5


def test_a_fantasy_price_does_not_move_the_median():
    """A 5300 EUR "RTX 4070 Ti" tower is really in the pool."""
    m = _market(*[("Gaming PC RTX 4070 Ti i7-13700K", p) for p in
                  (1200, 1500, 1650, 1700, 1800, 5300)])
    med, n = m.median_ask("gpu:rtx-4070-ti", cpu="i7")
    # [1200,1500,1650,1700,1800] survive the trim; 5300 does not.
    assert med == 1650 and n == 5, "the outlier is trimmed, not averaged in"


def test_laptops_never_enter_the_tower_pool():
    """"PC portable" is a bundle by token and would drag the tier to retail."""
    m = _market(*[("Gaming PC RTX 3060 i5-12400F", p) for p in (600, 650, 700, 700, 750)],
                ("PC portable gamer RTX 3060 i5", 1400),
                ("Laptop RTX 3060 i5", 1300))
    assert m.median_ask("gpu:rtx-3060", cpu="i5") == (700, 5)


def test_a_bare_card_is_not_a_tower():
    m = _market(*[("Gaming PC RTX 3060 i5-12400F", p) for p in (600, 650, 700, 700, 750)],
                ("Gigabyte RTX 3060 Gaming OC", 230))
    assert m.median_ask("gpu:rtx-3060", cpu="i5") == (700, 5)


def test_laptops_and_shop_towers_stay_out_of_the_tower_pool():
    """"PC Gaming HP OMEN i7-13700HX RTX4080" is a laptop whatever its title
    says, and a shop's shelf price is not what a private seller gets."""
    m = PCMarket(min_comparables=1)
    m.add("PC Gaming HP OMEN Intel i7-13700HX RTX4080", "", 1300, "a", CATALOG)
    m.add("PC gamer MSI Katana 15 i7-12650H RTX 4070", "", 1100, "b", CATALOG)
    m.add("PC Gamer RTX 3060 i5", "", 900, "c", CATALOG, owner_type="pro")
    m.add("PC Gamer RTX 3060 i5-12400F", "", 700, "d", CATALOG)
    assert m.median_ask("gpu:rtx-3060", cpu="i5") == (700, 1)
    assert m.median_ask("gpu:rtx-4080") == (None, 0) and m.median_ask("gpu:rtx-4070") == (None, 0)
