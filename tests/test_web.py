"""The board listens on 127.0.0.1, but any website open in the same browser
can still send it requests. Writes start live scraping from your IP, so they
must come from the board's own page."""
from techflip.web import _Handler


def _handler(**headers):
    h = _Handler.__new__(_Handler)
    h.headers = headers
    return h


def test_only_a_local_host_is_served():
    assert _handler(Host="127.0.0.1:8765")._local()
    assert _handler(Host="localhost:8765")._local()
    assert not _handler(Host="evil.example:8765")._local()      # DNS rebinding


def test_writes_must_come_from_the_board_page():
    ok = {"Host": "127.0.0.1:8765", "Content-Type": "application/json"}
    assert _handler(**ok)._same_origin_write()
    assert _handler(**ok, Origin="http://127.0.0.1:8765")._same_origin_write()
    assert not _handler(**ok, Origin="https://evil.example")._same_origin_write()
    assert not _handler(**{**ok, "Content-Type": "text/plain"})._same_origin_write()
