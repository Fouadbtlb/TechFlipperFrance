"""A tower's price is not set by its graphics card alone.

Keying comparables on the GPU only, a "GTX 1660 Super + i3-10100F" at 300 EUR
was valued at 542 and recommended as the best buy of the weekend. The owner's
reaction was immediate and correct: a 1660 Super with an i3 is not worth more
than 300.

The pool behind that number: 7 towers, spanning 300 to 950, not one of them an
i3. So the CPU has to be in the key, and a set that thin and that dispersed has
to be refused outright rather than averaged into a confident-looking figure.
"""
from techflip.pcmarket import PCMarket, cpu_tier
from techflip.pricing.catalog import load_catalog

CATALOG = load_catalog("config/pricebook.yaml")


def _market(*rows, min_comparables=5):
    m = PCMarket(min_comparables)
    for i, (title, price) in enumerate(rows):
        m.add(title, "", price, f"2ememain:{i}", CATALOG)
    return m


def test_the_cpu_tier_is_read_from_the_ad():
    assert cpu_tier("Gaming PC i3-10100F GTX 1660 Super") == "i3"
    assert cpu_tier("PC Gamer Ryzen 7 5800X RTX 4070") == "r7"
    assert cpu_tier("PC gamer RTX 3060") is None


def test_a_tower_is_compared_to_towers_with_a_similar_cpu():
    m = _market(*[(f"Gaming PC RTX 3060 i3-10100 {i}", p) for i, p in
                  enumerate((400, 420, 430, 450, 440))],
                *[(f"Gaming PC RTX 3060 Ryzen 9 5900X {i}", p) for i, p in
                  enumerate((900, 950, 1000, 1100, 1050))])
    cheap, _ = m.whole_value("gpu:rtx-3060", cpu="i3")
    dear, _ = m.whole_value("gpu:rtx-3060", cpu="r9")
    assert cheap is not None and dear is not None
    assert cheap < dear, "an i3 build must not inherit an r9 build's price"


def test_an_unmatched_cpu_falls_back_low_not_to_the_median():
    """Pooling every CPU together and taking the median puts a weak build at the
    middle of a range it sits at the bottom of. Unknown means assume the low
    end, the same posture as the unnamed-chassis credit."""
    prices = (600, 650, 700, 750, 800, 850)
    m = _market(*[(f"Gaming PC RTX 3060 build {i}", p) for i, p in enumerate(prices)])
    val, n = m.whole_value("gpu:rtx-3060", cpu="i3")   # no i3 comparables at all
    assert val is not None
    median_based = 725 * 0.85
    assert val < median_based, f"{val} should sit below the pooled median"


def test_a_set_too_scattered_to_mean_anything_is_refused():
    """The real 1660 Super pool: 7 towers from 300 to 950. A median over that is
    not an estimate, it is a coin flip dressed as one."""
    m = _market(*[(f"Gaming PC GTX 1660 Super {i}", p) for i, p in
                  enumerate((300, 350, 375, 600, 800, 950, 675))])
    val, n = m.whole_value("gpu:gtx-1660-super", cpu="i3")
    assert val is None, f"claimed {val} from a 300-950 spread"


def test_a_tight_set_is_still_trusted():
    m = _market(*[(f"Gaming PC RTX 3060 i5 {i}", p) for i, p in
                  enumerate((650, 680, 700, 700, 720, 740))])
    val, n = m.whole_value("gpu:rtx-3060", cpu="i5")
    assert val is not None and n >= 5
