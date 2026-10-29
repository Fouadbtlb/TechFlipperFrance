"""Cash Converters stores are placed by postcode, not by guessing the name.

pgeocode's name search put HUY in Lathuy (35 km off), MARCHE in Marchienne-au-
Pont, a Charleroi suburb, instead of Marche-en-Famenne (80 km off), and could
not place LIEGE or LA LOUVIERE at all. Every distance and fuel figure for those
four shops was wrong; Marche read as 9 km from Charleroi. Same lesson as Cash
Express, whose name search put LILLE CENTRE in Lillebonne.
"""
from techflip.geo import haversine
from techflip.sources.cashconverters import _geocode

TRUTH = {                        # town centres
    "HUY": (50.5187, 5.2394),
    "MARCHE": (50.2266, 5.3443),
    "LA LOUVIERE": (50.4796, 4.1866),
    "LIEGE": (50.6326, 5.5797),
    "COUILLET": (50.3914, 4.4591),
    "FROYENNES": (50.6219, 3.3546),
}


def test_every_store_lands_in_its_own_town(belgian_postcodes):
    for store, (lat, lng) in TRUTH.items():
        got = _geocode(store)
        assert got is not None, store
        assert haversine(lat, lng, *got) < 8, (store, got)
