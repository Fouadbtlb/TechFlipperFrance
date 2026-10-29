"""The web build has no geocoder, so the app asks the server for a town."""
from techflip.geo import find_place


def test_towns_and_postcodes_resolve(postcodes):
    assert find_place("Lille")["label"] == "Lille"
    assert find_place("59000")["label"] == "Lille"
    assert find_place("Charleroi") is not None      # Belgian town
    assert find_place("7700") is not None           # Belgian postcode (Mouscron)


def test_a_near_miss_is_not_a_hit(postcodes):
    # pgeocode's fuzzy search ranks Lillebonne first for "Lille"; only exact names count.
    assert find_place("Lillebon") is None
    assert find_place("") is None
