"""How the scrapers talk to the sites: through the proxy from the first
request, newest ads first, and a liveness check narrow enough to trust."""
import lbc
import pytest

from techflip.sources import leboncoin as lbc_source
from techflip.sources.leboncoin import LeboncoinSource, _lbc_proxy, _newest_first


class _Client:
    """Stands in for lbc.Client: records how it was built and what it searched."""
    made: list = []

    def __init__(self, **kw):
        _Client.made.append(kw)
        self.urls = []
        self.ads = []

    def search(self, url, **kw):
        self.urls.append(url)
        return type("R", (), {"ads": self.ads})()


def test_the_proxy_is_given_to_lbc_at_construction(monkeypatch):
    """lbc makes its cookie request while it is built and rebuilds its session
    after a DataDome block from the proxy it was given: a proxy set afterwards
    lets both go out from the real IP."""
    monkeypatch.setattr(lbc_source.lbc, "Client", _Client)
    src = LeboncoinSource(proxy="http://user:p%40ss@proxy.example:8080")
    assert src.client is not None                # built on first use, with the proxy
    proxy = _Client.made[-1]["proxy"]
    assert isinstance(proxy, lbc.Proxy)
    assert proxy.url == "http://user:p%40ss@proxy.example:8080"


def test_no_proxy_means_direct_and_a_bad_one_fails_loudly():
    assert _lbc_proxy(None) is None
    with pytest.raises(ValueError):
        _lbc_proxy("proxy.example")


def test_searches_ask_for_the_newest_ads():
    """lbc ignores its `sort` argument when given a URL, so the order goes in the URL."""
    assert _newest_first("https://www.leboncoin.fr/recherche?category=43&text=ps5").endswith(
        "&sort=time&order=desc")
    assert _newest_first("https://www.leboncoin.fr/recherche?text=ps5&sort=price&order=asc").endswith(
        "sort=price&order=asc")


def test_liveness_searches_narrowly_around_the_listing(monkeypatch):
    monkeypatch.setattr(lbc_source.lbc, "Client", _Client)
    src = LeboncoinSource()
    row = {"title": "PS5 Slim edition disque", "price": 300.0, "lat": 50.63, "lng": 3.06, "source_id": "42"}
    src.client.ads = [type("Ad", (), {"id": 42})()]
    assert src.is_online(row) is True
    url = src.client.urls[-1]
    assert "text=ps5 slim edition disque" in url and "price=180-331" in url
    assert "locations=zone__50.63_3.06_10000_10000" in url
    src.client.ads = []
    assert src.is_online(row) is False
    assert src.is_online({**row, "lat": None}) is None          # cannot search narrowly: no answer


def test_an_unreachable_leboncoin_does_not_stop_the_scanner_starting(monkeypatch):
    def down(**kw):
        raise ConnectionError("unreachable")
    monkeypatch.setattr(lbc_source.lbc, "Client", down)
    src = LeboncoinSource()                      # no request yet
    with pytest.raises(ConnectionError):
        src.fetch(type("S", (), {"url": "https://www.leboncoin.fr/recherche?text=ps5", "name": "x"})())
