"""Distances are measured from wherever you start (HOME_LAT / HOME_LNG): a
tower 20 km from Namur reads as 110 km from Lille."""
from techflip.geo import LILLE, Locator, haversine

NAMUR = (50.4674, 4.8720)


def test_the_default_origin_is_lille():
    # Menen, on the border, is ~20km from Lille.
    assert 15 < Locator().distance(lat=50.80, lng=3.16) < 25


def test_an_origin_can_be_chosen():
    menen = dict(lat=50.80, lng=3.16)
    assert Locator(origin=NAMUR).distance(**menen) > 90
    assert Locator(origin=LILLE).distance(**menen) < 25


def test_a_listing_beside_namur_is_near_from_namur():
    jambes = dict(lat=50.4569, lng=4.8722)          # across the Meuse from Namur
    assert Locator(origin=NAMUR).distance(**jambes) < 5
    assert Locator(origin=LILLE).distance(**jambes) > 100
    assert 125 < haversine(*LILLE, *NAMUR) < 135
