"""Distances are measured from wherever you are actually going.

Every distance in this tool is to Lille, hardcoded. That is right for the daily
scan and wrong for a trip: a tower 20km from Namur reads as 110km and gets
filtered out of a weekend that is going to Namur anyway.
"""
from techflip.geo import LILLE, NAMUR, Locator, haversine


def test_the_default_origin_is_still_lille():
    loc = Locator()
    # Menen, on the border, is ~20km from Lille.
    assert 15 < loc.distance(lat=50.80, lng=3.16) < 25


def test_an_origin_can_be_chosen():
    menen = dict(lat=50.80, lng=3.16)
    assert Locator(origin=NAMUR).distance(**menen) > 90
    assert Locator(origin=LILLE).distance(**menen) < 25


def test_a_listing_beside_namur_is_near_from_namur():
    # Jambes, right across the Meuse from Namur centre.
    jambes = dict(lat=50.4569, lng=4.8722)
    assert Locator(origin=NAMUR).distance(**jambes) < 5
    assert Locator(origin=LILLE).distance(**jambes) > 100


def test_namur_is_where_it_should_be():
    assert 125 < haversine(*LILLE, *NAMUR) < 135      # ~129 km a vol d oiseau
