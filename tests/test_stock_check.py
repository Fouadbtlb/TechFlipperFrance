"""Confirm a shop item is still buyable before it is recommended.

A shop's search feed lags its own product pages. On 2026-09-29 the Cash
Converters feed still listed five Galaxy S26 at 300 EUR, with a valid
add-to-cart link, hours after every one of those product pages had gone. The
reverse also happens: a Cash Express tower read in stock in the index and
"rupture de stock" on its page. So the feed says what to look at, and the page
says whether it is real.
"""
from techflip.liveness import page_online


class _Resp:
    def __init__(self, text, code=200):
        self.text = text
        self.status_code = code


PAGE = "<html>" + "x" * 2000


def test_a_page_with_a_cart_button_is_online():
    assert page_online(_Resp(PAGE + "Ajouter au panier</html>")) is True


def test_rupture_de_stock_beats_the_cart_button():
    """Both strings appear on the same page; the out-of-stock notice wins."""
    assert page_online(_Resp(PAGE + "Ajouter au panier ... Rupture de stock</html>")) is False


def test_an_empty_or_missing_page_means_gone():
    assert page_online(_Resp("", 200)) is False
    assert page_online(_Resp("<html>tiny</html>", 200)) is False
    assert page_online(_Resp(PAGE, 404)) is False
    assert page_online(_Resp(PAGE, 410)) is False


def test_a_shop_that_does_not_really_answer_says_nothing():
    """A block page or a server error is not proof the item sold."""
    assert page_online(_Resp(PAGE, 403)) is None
    assert page_online(_Resp("", 502)) is None
