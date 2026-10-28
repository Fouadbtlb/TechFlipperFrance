from techflip.geo import Locator
from techflip.sources.deuxememain import DeuxiemeMainSource, _with_offset


def test_normalize_captures_latlng_and_price():
    src = DeuxiemeMainSource.__new__(DeuxiemeMainSource)
    it = {
        "itemId": "m123", "title": "Playstation 5", "vipUrl": "/v/x/m123",
        "priceInfo": {"priceCents": 50000},
        "location": {"cityName": "Tournai", "countryAbbreviation": "BE",
                     "latitude": 50.6071, "longitude": 3.3892},
        "sellerInformation": {"sellerId": 9},
    }
    l = src._normalize(it, "PS5 BE")
    assert l.price == 500.0 and l.country == "BE"
    assert l.lat == 50.6071 and l.lng == 3.3892
    assert l.url == "https://www.2ememain.be/v/x/m123"


def test_offset_pagination():
    assert "offset=30" in _with_offset("https://x/api?query=ps5&offset=0&limit=30", 30)


def test_belgian_border_is_easy_zone():
    d = Locator().distance(lat=50.6071, lng=3.3892)  # Tournai ~25km from Lille
    assert d is not None and d < 60
