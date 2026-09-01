"""A margin you have to drive 120km for is not the margin you keep.

Every figure this tool showed was gross. At the owner's own estimate of 3 EUR a
litre, a round trip to Aywaille costs more than several of the "deals" it was
recommending were worth.
"""
from techflip.geo import ANDENNE, LILLE, NAMUR, Locator, fuel_cost, haversine


def test_a_round_trip_costs_both_ways():
    one_way = fuel_cost(100, price_per_litre=3.0, litres_per_100km=7.0,
                        round_trip=False)
    there_and_back = fuel_cost(100, price_per_litre=3.0, litres_per_100km=7.0)
    assert one_way == 21.0                      # 100km * 0.07 L/km * 3 EUR
    assert there_and_back == 42.0


def test_an_unknown_distance_costs_nothing_rather_than_crashing():
    assert fuel_cost(None) is None


def test_andenne_is_east_of_namur():
    assert 15 < haversine(*NAMUR, *ANDENNE) < 30
    assert 130 < haversine(*LILLE, *ANDENNE) < 160


def test_the_locator_measures_from_andenne_too():
    jambes = dict(lat=50.4569, lng=4.8722)
    assert Locator(origin=ANDENNE).distance(**jambes) < 30
    assert Locator(origin=LILLE).distance(**jambes) > 100
