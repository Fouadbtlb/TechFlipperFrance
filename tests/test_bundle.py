"""Whole machines must never set a single part's reference price.

Every title here is verbatim from the live 2ememain pool. Before the compound
check, "Gamepc" read as a single unknown token, so a 1500 EUR tower taught the
tracker that an RTX 4070 costs 1350.
"""
from techflip.pricing.extract import is_bundle, teaches_price


def test_dutch_and_english_machine_compounds_are_bundles():
    for title in [
        "RTX 3080 / Ryzen 7 3700X / 32GB DDR4  Gamepc",
        "Gamepc met rtx 3070",
        "Gaming PC RTX 4070",
        "Desktop RTX 3060 i5",
        "Complete gamingpc RTX 4060",
    ]:
        assert is_bundle(title), title


def test_a_bare_card_is_not_a_bundle():
    for title in [
        "Gigabyte GeForce RTX 3070 Gaming OC 8G",
        "Sapphire PURE AMD Radeon RX 7800 XT 16GB graphics card",
        "GeForce GTX 1660 SUPER AERO ITX OC",
        "MSI GeForce GTX 1060 AERO ITX 3G OC videokaart",
    ]:
        assert not is_bundle(title), title


def test_an_accessory_that_merely_mentions_pc_is_not_a_tower():
    """Verbatim live titles. "pc" here is a compatibility list, not the thing
    for sale, and reading them as towers both filled the PC shopping board with
    100 EUR gamepads and let the description be mined for parts the ad never
    contained."""
    for title in [
        "Manette SCUF pc ps5 Xbox",
        "Volant de jeu Xbox /PC — Trustmaster T128x avec interrupteur",
        "Casque gaming PC PS5 Xbox",
        "Boitier PC Asus A31 plus, 10 ventilateur, hub",
    ]:
        assert not is_bundle(title), title


def test_a_tower_sold_with_extras_is_still_a_tower():
    """The machine comes first when the machine is what is for sale."""
    for title in [
        "PC Gamer complet + manette + ecran",
        "Pc gamer RTX 3060 avec clavier souris",
        "Gaming PC met controller",
    ]:
        assert is_bundle(title), title


def test_a_machine_never_teaches_a_part_price():
    assert not (not is_bundle("Gamepc met rtx 3070")
                and teaches_price("Gamepc met rtx 3070"))


def test_recompute_purges_pre_rule_contamination(tmp_path):
    """Rows ingested before a rule existed keep their old primary_component and
    keep poisoning the median. A live pool had bundles setting the price of a
    bare Xbox Series X long after the rule to exclude them shipped."""
    from techflip.domain import Listing
    from techflip.pricing.catalog import load_catalog
    from techflip.pricing.identify import teaching_key
    from techflip.storage import Store

    store = Store(tmp_path / "t.db")
    catalog = load_catalog("config/pricebook.yaml")

    def add(uid, title, price, primary):
        l = Listing(source="2ememain", source_id=uid, url="u", title=title,
                    price=price, published_at="2026-08-11", description="",
                    city="Gent", search_name="Xbox")
        store.upsert_listing(l)
        store.set_primary_component(l.uid, primary, True)   # as an old build wrote it

    add("1", "XBOX Series X", 450, "console:xbox-series-x")
    add("2", "Xbox Series X (1 To) + 2 manettes", 450, "console:xbox-series-x")
    add("3", "Xbox Series X 1TB + Manette Pro ASUS ROG Raikiri", 500, "console:xbox-series-x")

    assert len(store.component_prices("console:xbox-series-x", "1970-01-01")) == 3
    stats = store.retrack(lambda l: teaching_key(l, catalog))

    assert stats["scanned"] == 3 and stats["changed"] == 2
    assert store.component_prices("console:xbox-series-x", "1970-01-01") == [450]
