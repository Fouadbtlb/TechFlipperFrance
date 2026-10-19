"""Is this listing still buyable, right now?

The pool is built from search feeds, and a feed lags the product pages behind
it. Cash Converters listed five Galaxy S26 at 300 EUR with working add-to-cart
links for hours after those pages had died, and the owner was sent to buy
them. Cash Express does the opposite, keeping an item in its index that its own
page calls "rupture de stock".

A feed is therefore a shortlist, not a promise. This asks the page.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# A real product page is tens of kilobytes. A deleted one on these sites comes
# back as an empty body or a stub rather than an honest 404.
_MIN_BODY = 800
_GONE_CODES = {404, 410}
_OUT = ("rupture de stock", "out of stock", "niet meer beschikbaar",
        "n'est plus disponible", "plus disponible")
_CART = ("ajouter au panier", "add-to-cart", "add to cart", "in winkelwagen")


def status_from_page(resp) -> str:
    """in_stock | out_of_stock | gone, from one fetched page."""
    body = getattr(resp, "text", "") or ""
    code = getattr(resp, "status_code", 200)
    if code in _GONE_CODES or len(body) < _MIN_BODY:
        return "gone"
    low = body.lower()
    # Order matters: a shop page carries the cart markup even when the notice
    # above it says the item has walked out of the door.
    if any(w in low for w in _OUT):
        return "out_of_stock"
    if any(w in low for w in _CART):
        return "in_stock"
    # Marketplaces have no cart. A page that loads with a real body is live.
    return "in_stock"


def verify(urls, session=None, sleep: float = 0.4, timeout: float = 25.0) -> dict:
    """{url: status}. A fetch that fails is "unknown", never "in_stock":
    silence must not be mistaken for confirmation."""
    if session is None:
        import requests
        session = requests.Session()
    out: dict[str, str] = {}
    for i, url in enumerate(urls):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"})
            out[url] = status_from_page(r)
        except Exception as e:
            log.warning("stock: %s: %s", url, type(e).__name__)
            out[url] = "unknown"
        if sleep and i + 1 < len(urls):
            time.sleep(sleep)
    return out
