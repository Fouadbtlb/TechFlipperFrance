from techflip.geo import LILLE, Locator, haversine, logistics_cost, zone_for_distance


def test_haversine_known_distances():
    # Lille -> Paris is roughly 205 km
    assert 195 <= haversine(*LILLE, 48.8600, 2.3400) <= 215
    assert haversine(*LILLE, *LILLE) == 0


def test_zone_thresholds():
    assert zone_for_distance(0) == "EASY"
    assert zone_for_distance(60) == "EASY"
    assert zone_for_distance(61) == "MEDIUM"
    assert zone_for_distance(150) == "MEDIUM"
    assert zone_for_distance(151) == "HARD"
    assert zone_for_distance(None) == "HARD"


def test_logistics_cost_picks_cheapest():
    # near pickup beats shipping
    assert logistics_cost(20, "parcel", shippable=True, cost_per_km=0.25) == 10.0
    # far but shippable -> shipping wins
    assert logistics_cost(300, "parcel", shippable=True, cost_per_km=0.25) == 12.0
    # far, not shippable -> expensive drive only
    assert logistics_cost(300, "bulky", shippable=False, cost_per_km=0.25) == 150.0
    # unknown distance, not shippable -> cannot cost it
    assert logistics_cost(None, "bulky", shippable=False) is None


def test_locator_with_injected_resolver():
    loc = Locator(resolver=lambda z: {"59000": LILLE, "75001": (48.86, 2.34)}.get(z))
    assert loc.distance_to_lille("59000") == 0.0
    assert loc.distance_to_lille("75001") and loc.distance_to_lille("75001") > 190
    assert loc.distance_to_lille("00000") is None
    assert loc.distance_to_lille(None) is None


def test_anchor_fallback_zones_near_ring():
    loc = Locator()  # no pgeocode installed here -> anchor table
    assert zone_for_distance(loc.distance_to_lille("62000")) == "EASY"      # Arras
    assert zone_for_distance(loc.distance_to_lille("80000")) == "MEDIUM"    # Amiens
    assert zone_for_distance(loc.distance_to_lille("75001")) == "HARD"      # Paris
