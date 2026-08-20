from techflip.buying import (Buy, WHITE_MARKERS, catalog_queries,
                             looks_like_sales_copy, rank_buys)
from techflip.pricing.catalog import load_catalog


def _buy(label, price, value, white=False):
    return Buy(key=f"gpu:{label}", label=label, price=price, value=value,
               discount=value - price, zone="EASY", distance=20.0, white=white,
               title=label, url="u", city="Lille")


def test_ranks_best_hardware_first_then_cheapest():
    buys = [_buy("RTX 3070", 300, 320), _buy("RTX 3080", 400, 430),
            _buy("RTX 3080", 380, 430), _buy("RTX 3060", 200, 260)]
    picks = rank_buys(buys, budget=500)
    assert [(b.label, b.price) for b in picks] == [
        ("RTX 3080", 380), ("RTX 3080", 400), ("RTX 3070", 300), ("RTX 3060", 200)]


def test_over_budget_is_excluded_and_bait_is_dropped():
    buys = [_buy("RTX 3070", 300, 320), _buy("RTX 4090", 1500, 1500),
            _buy("RTX 3080", 1, 430)]          # 1 EUR "stock" ad = bait
    picks = rank_buys(buys, budget=400)
    assert [b.label for b in picks] == ["RTX 3070"]


def test_white_only_keeps_white_cards():
    buys = [_buy("RTX 3080", 400, 430), _buy("RTX 3070", 300, 320, white=True)]
    assert [b.label for b in rank_buys(buys, 500, white_only=True)] == ["RTX 3070"]


def test_white_markers_match_real_listing_titles():
    assert WHITE_MARKERS.search("ASUS ROG Strix RTX 3070 White Edition V2")
    assert WHITE_MARKERS.search("Gigabyte GeForce RTX 3080 Vision OC")
    assert WHITE_MARKERS.search("Carte graphique blanche")
    assert not WHITE_MARKERS.search("Gigabyte RTX 3070 Gaming OC 8GB")


def test_flags_manufacturer_copy_but_not_a_real_seller():
    # verbatim from a live 2ememain ad that paired a press render with a price
    # 120 EUR under market
    assert looks_like_sales_copy(
        "Experience high-end gaming performance with this premium sapphire "
        "technology amd gpu, known for its excellent build quality and cooling. "
        "Specs include: • boost clock up to 2475 mhz • game clock • 16gb")
    assert not looks_like_sales_copy(
        "Gigabyte vision geforce rtx 3080 10gb uitstekende staat custom koelpads "
        "de kaart kan ter plekke getest worden indien gewenst.")
    assert not looks_like_sales_copy("")


def test_queries_come_from_the_catalog():
    catalog = load_catalog("config/pricebook.yaml")
    q = catalog_queries(catalog, "gpu")
    assert "RTX 3080" in q and "RX 6750 XT" in q
    assert len(q) > 30                      # coverage grows with the pricebook
    assert all(d.category == "gpu" for d in catalog.defs if d.label in q)
