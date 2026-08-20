"""Shopping mode: rank the whole stored pool as a buy list.

The alert pipeline judges an ad once, the minute it appears. These tests pin
the other half: an ad that has been sitting for three weeks is still a fine
purchase, and a tower is worth what its parts are worth whatever its age.
"""
import datetime as dt

import pytest

from techflip.domain import Listing
from techflip.geo import Locator
from techflip.hunt import Find, evaluate, filter_finds, rank, scan
from techflip.pricing.appraise import REALIZATION
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


@pytest.fixture
def ctx(tmp_path):
    store = Store(tmp_path / "t.db")
    tracker = PriceTracker(store, CATALOG, min_comparables=5, window_days=90)
    return store, tracker, Locator()


def _listing(title, price, **kw):
    kw.setdefault("published_at", dt.date.today().isoformat())
    return Listing(
        source=kw.pop("source", "2ememain"),
        source_id=kw.pop("source_id", title[:20]),
        url="https://example.test/ad",
        title=title,
        price=price,
        description=kw.pop("description", ""),
        lat=kw.pop("lat", 50.80), lng=kw.pop("lng", 3.16),   # Menen, ~20km
        city=kw.pop("city", "Menen"),
        **kw,
    )


def test_a_cheap_console_is_found_with_its_saving(ctx):
    store, tracker, locator = ctx
    f = evaluate(_listing("Xbox Series S", 110), CATALOG, tracker, locator)
    assert f.kind == "single"
    assert f.category == "console"
    assert f.parts == ("Xbox Series S",)
    # seed 160, console realization 0.92 -> ~147 realizable, so ~37 under market
    assert f.value == pytest.approx(147.2, abs=1)
    assert f.savings == pytest.approx(37.2, abs=1)
    assert f.zone == "EASY"


def test_a_whole_tower_is_valued_on_its_parts(ctx):
    """The part-out thesis: a bundle's worth is the sum of what is inside it,
    which is exactly the number a buyer needs and the one `buy` refused to
    compute because it skipped every bundle."""
    store, tracker, locator = ctx
    tower = evaluate(
        _listing("PC Gamer RTX 3060 Ryzen 5 5600 16Go DDR4 1To NVMe", 250),
        CATALOG, tracker, locator)
    card_alone = evaluate(_listing("RTX 3060", 250, source_id="card"),
                          CATALOG, tracker, locator)
    assert tower.kind == "build"
    assert tower.category == "pc"
    assert tower.n_priced >= 3
    # Worth strictly more than the card inside it. That summed number is what
    # `buy` could never produce, because it discarded every bundle outright.
    assert tower.value > card_alone.value
    assert tower.savings > 0


def test_a_tower_is_credited_for_the_parts_no_ad_ever_lists(ctx):
    """Nobody writes the motherboard, PSU, case and cooler in a PC ad, but the
    machine physically contains them. Summing only the headline parts valued
    every tower below its asking price, which is why no PC ever surfaced: a
    550 EUR "Ryzen 5 5600 + RX 5700XT + 16GB" came back at 280.
    """
    store, tracker, locator = ctx
    tower = evaluate(_listing("PC Gamer RTX 3060 Ryzen 5 5600 16Go DDR4", 250),
                     CATALOG, tracker, locator)
    named = sum(b["value"] for b in
                _appraise_parts("PC Gamer RTX 3060 Ryzen 5 5600 16Go DDR4", tracker))
    assert tower.value > named
    assert any("carte mere" in l.lower() or "chassis" in l.lower() for l in tower.lines)


def test_the_chassis_credit_is_not_given_twice(ctx):
    """An ad that does name its motherboard must not be paid for two of them."""
    store, tracker, locator = ctx
    silent = evaluate(_listing("PC Gamer RTX 3060 Ryzen 5 5600", 250),
                      CATALOG, tracker, locator)
    explicit = evaluate(_listing("PC Gamer RTX 3060 Ryzen 5 5600 B550 650W", 250,
                                 source_id="x"), CATALOG, tracker, locator)
    named = [l for l in explicit.lines
             if "carte mere" in l.lower() and "chassis" not in l.lower()]
    credited = [l for l in explicit.lines
                if "carte mere" in l.lower() and "chassis" in l.lower()]
    assert named, "the B550 named in the ad should be valued for real"
    assert not credited, "and must not also draw the unnamed-board credit"
    board = CATALOG.by_key["mobo:am4"].seed * REALIZATION["motherboard"]
    assert explicit.value < silent.value + board


def test_a_laptop_is_not_a_tower_and_says_so(ctx):
    """"PC portable" contains "pc", so a laptop read as a tower and collected a
    credit for a motherboard, an ATX PSU and a case it does not have. Its parts
    are also priced from the desktop pricebook, and a mobile RTX 3050 is worth
    a fraction of the desktop card, so the ad has to carry that warning."""
    store, tracker, locator = ctx
    lap = evaluate(_listing("PC Portable Gamer ASUS TUF - 32Go RAM / RTX 3050", 400),
                   CATALOG, tracker, locator)
    assert "laptop" in lap.flags
    assert not any("chassis" in l.lower() for l in lap.lines)


def test_a_single_item_gets_no_chassis_credit(ctx):
    store, tracker, locator = ctx
    card = evaluate(_listing("RTX 3060", 180), CATALOG, tracker, locator)
    assert card.kind == "single"
    assert not any("chassis" in l.lower() for l in card.lines)


def _appraise_parts(title, tracker):
    from techflip.pricing.appraise import appraise, build_items
    from techflip.pricing.extract import recognize
    appr = appraise(build_items(recognize(title, "", CATALOG), None, CATALOG, title),
                    tracker, 0.85)
    return [b for b in appr.breakdown if b.get("value")]


def test_a_wanted_ad_is_not_an_offer(ctx):
    """"Recherche ps5 standard" was the third-best deal on the board: someone
    LOOKING to buy a PS5, appraised as though they were selling one. The alert
    path drops these via `default_exclude` in searches.yaml, which the board
    never applied because it reads the database directly."""
    for title in ["Recherche ps5 standard", "Cherche PS5 pas cher",
                  "Achète Xbox Series X", "Gezocht: playstation 5",
                  "Op zoek naar een Nintendo Switch", "Wanted: RTX 3070"]:
        assert evaluate(_listing(title, 200, source_id=title[:12]),
                        CATALOG, tracker_of(ctx), ctx[2]) is None, title


def test_a_real_sale_is_not_mistaken_for_a_wanted_ad(ctx):
    for title in ["Ps5 à vendre urgent", "PS5 recherchee par tous, tres bon etat",
                  "Xbox Series X complete"]:
        assert evaluate(_listing(title, 200, source_id=title[:12]),
                        CATALOG, tracker_of(ctx), ctx[2]) is not None, title


def tracker_of(ctx):
    return ctx[1]


def test_an_unrecognised_ad_is_not_a_find(ctx):
    store, tracker, locator = ctx
    assert evaluate(_listing("Lot de cables HDMI", 15), CATALOG, tracker, locator) is None


def test_a_price_far_under_market_is_flagged_as_bait(ctx):
    store, tracker, locator = ctx
    f = evaluate(_listing("PS5", 80), CATALOG, tracker, locator)
    assert "bait" in f.flags


def test_a_broken_item_is_flagged_and_discounted(ctx):
    store, tracker, locator = ctx
    ok = evaluate(_listing("Xbox Series X", 300), CATALOG, tracker, locator)
    hs = evaluate(_listing("Xbox Series X", 300, description="en panne, ne s'allume plus"),
                  CATALOG, tracker, locator)
    assert "broken" in hs.flags and "broken" not in ok.flags
    assert hs.value < ok.value


def test_filters_narrow_by_budget_category_and_distance(ctx):
    store, tracker, locator = ctx
    near = evaluate(_listing("Xbox Series S", 110), CATALOG, tracker, locator)
    far = evaluate(_listing("Xbox Series S", 110, source_id="far",
                            lat=48.86, lng=2.34, city="Paris"),
                   CATALOG, tracker, locator)
    dear = evaluate(_listing("PS5", 400, source_id="dear"), CATALOG, tracker, locator)
    gpu = evaluate(_listing("RTX 3060", 180, source_id="gpu"), CATALOG, tracker, locator)
    finds = [near, far, dear, gpu]

    assert filter_finds(finds, budget=150) == [near, far]
    assert filter_finds(finds, category="console") == [near, far, dear]
    assert filter_finds(finds, category="gpu") == [gpu]
    assert filter_finds(finds, max_km=60) == [near, dear, gpu]
    assert filter_finds(finds, query="xbox") == [near, far]


def test_bait_sinks_below_honest_offers(ctx):
    store, tracker, locator = ctx
    bait = evaluate(_listing("PS5", 80), CATALOG, tracker, locator)
    real = evaluate(_listing("Xbox Series S", 110, source_id="s"), CATALOG, tracker, locator)
    assert bait.savings > real.savings          # on paper the bait looks better
    assert rank([bait, real], "savings")[0] is real


def test_scan_reads_every_stored_row_however_old(ctx):
    """No date filter anywhere: `recent_unalerted` hides anything older than a
    week, which is most of the pool and most of what is actually buyable."""
    store, tracker, locator = ctx
    old = _listing("Xbox Series S", 110, source_id="old", published_at="2026-01-04")
    store.upsert_listing(old)
    store.upsert_listing(_listing("RTX 3060", 180, source_id="new"))

    finds = scan(store, CATALOG, tracker, locator)
    assert {f.uid for f in finds} == {old.uid, "2ememain:new"}


def test_scan_reports_a_price_cut_and_time_on_market(ctx):
    """The two facts a haggler actually wants, and neither was ever shown: how
    long the seller has been failing to sell, and whether they have already
    blinked once on price."""
    store, tracker, locator = ctx
    l = _listing("Xbox Series X", 400, source_id="sat")
    store.upsert_listing(l)
    store.upsert_listing(_listing("Xbox Series X", 340, source_id="sat"))
    store.conn.execute("UPDATE listings SET first_seen='2026-08-01T09:00:00+00:00', "
                       "last_seen='2026-08-15T09:00:00+00:00'")
    store.conn.commit()

    f = scan(store, CATALOG, tracker, locator)[0]
    assert f.price == 340
    assert f.price_cut == {"first": 400, "current": 340, "cut": 60.0,
                           "pct": 0.15, "changes": 1}
    assert f.days_listed == 14.0
    assert "cut" in f.flags and "sitting" in f.flags


def test_a_fresh_untouched_ad_carries_neither_flag(ctx):
    store, tracker, locator = ctx
    store.upsert_listing(_listing("Xbox Series X", 340, source_id="new"))
    f = scan(store, CATALOG, tracker, locator)[0]
    assert f.price_cut is None
    assert "cut" not in f.flags and "sitting" not in f.flags


def test_a_listing_confirmed_gone_leaves_the_board(ctx):
    """Handing out a dead link is worse than showing nothing: it is the point
    at which the person stops trusting every other row too."""
    store, tracker, locator = ctx
    store.upsert_listing(_listing("Xbox Series X", 300, source_id="sold"))
    store.upsert_listing(_listing("Xbox Series X", 300, source_id="live"))
    assert len(scan(store, CATALOG, tracker, locator)) == 2

    store.mark_gone("2ememain:sold")
    assert [f.uid for f in scan(store, CATALOG, tracker, locator)] == ["2ememain:live"]


def test_hidden_and_interested_picks_survive_a_restart(tmp_path):
    store = Store(tmp_path / "t.db")
    store.set_pick("2ememain:1", "interested", note="a voir samedi")
    store.set_pick("2ememain:2", "hidden")
    reopened = Store(tmp_path / "t.db")
    picks = reopened.picks()
    assert picks["2ememain:1"]["state"] == "interested"
    assert picks["2ememain:1"]["note"] == "a voir samedi"
    assert picks["2ememain:2"]["state"] == "hidden"

    reopened.set_pick("2ememain:2", "none")
    assert "2ememain:2" not in reopened.picks()


def test_a_handheld_console_is_not_flagged_as_a_laptop(ctx):
    """A Switch ad says "console portable" because that is what a Switch is.
    Flagging it as a laptop told the reader its value was computed from desktop
    part prices, which is both false and alarming on a 90 EUR console."""
    store, tracker, locator = ctx
    f = evaluate(_listing("Nintendo Switch OLED", 90,
                          description="console portable, tres bon etat"),
                 CATALOG, tracker, locator)
    assert "laptop" not in f.flags


def test_a_real_laptop_is_still_flagged(ctx):
    store, tracker, locator = ctx
    f = evaluate(_listing("PC Portable Gamer ASUS TUF RTX 3050", 400, source_id="lap"),
                 CATALOG, tracker, locator)
    assert "laptop" in f.flags
