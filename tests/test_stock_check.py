"""Confirm an item is still buyable before it is recommended.

A shop's search feed lags its own product pages. On 2026-09-29 the Cash
Converters feed still listed five Galaxy S26 at 300 EUR, with a valid
add-to-cart link, hours after every one of those product pages had gone. The
owner was told to go and buy them. The reverse also happens: a Cash Express
tower read in stock in the index and "rupture de stock" on its page.

So the feed says what to look at, and the page says whether it is real.
"""
from techflip.stock import status_from_page, verify


class _Resp:
    def __init__(self, text, code=200):
        self.text = text
        self.status_code = code


def test_a_page_with_a_cart_button_is_in_stock():
    assert status_from_page(_Resp("<html>" + "x" * 2000 + "Ajouter au panier</html>")) == "in_stock"
    assert status_from_page(_Resp("<html>" + "x" * 2000 + 'id="add-to-cart"</html>')) == "in_stock"


def test_rupture_de_stock_beats_the_cart_button():
    """Both strings appear on the same page; the out-of-stock notice wins."""
    page = "<html>" + "x" * 2000 + "Ajouter au panier ... Rupture de stock</html>"
    assert status_from_page(_Resp(page)) == "out_of_stock"


def test_an_empty_or_missing_page_means_gone():
    assert status_from_page(_Resp("", 200)) == "gone"
    assert status_from_page(_Resp("<html>tiny</html>", 200)) == "gone"
    assert status_from_page(_Resp("<html>" + "x" * 2000 + "</html>", 404)) == "gone"
    assert status_from_page(_Resp("<html>" + "x" * 2000 + "</html>", 410)) == "gone"


def test_a_marketplace_page_that_loads_is_alive():
    """2ememain has no cart button; HTTP 200 with a real body is the signal."""
    assert status_from_page(_Resp("<html>" + "x" * 5000 + "</html>", 200)) == "in_stock"


def test_verify_labels_each_url_and_never_raises():
    class _Session:
        def get(self, url, **kw):
            if "boom" in url:
                raise RuntimeError("timeout")
            if "sold" in url:
                return _Resp("", 200)
            return _Resp("<html>" + "x" * 3000 + "Ajouter au panier</html>")

    out = verify(["http://x/ok", "http://x/sold", "http://x/boom"],
                 session=_Session(), sleep=0)
    assert out["http://x/ok"] == "in_stock"
    assert out["http://x/sold"] == "gone"
    assert out["http://x/boom"] == "unknown"
