from techflip.domain import Listing
from techflip.filters import price_prefilter, scam_marker, text_prefilter


def _l(title, desc="", price=200.0):
    return Listing(source="leboncoin", source_id="1", url="x", title=title,
                   price=price, published_at=None, description=desc)


def test_price_band_still_enforced():
    ok, _ = price_prefilter(_l("RTX 4070", price=10), 20, None, 1500)
    assert not ok


def test_icloud_lock_is_hard_rejected():
    ok, why = price_prefilter(_l("iPhone 13", "vendu tel quel, bloque iCloud"), 20, None, 1500)
    assert not ok and "verrouillage" in why


def test_bios_lock_rejected_accent_insensitive():
    assert scam_marker(_l("Latitude 7400", "mot de passe BIOS oublie")) is not None
    assert scam_marker(_l("EliteBook", "BIOS verrouillé")) is not None


def test_box_only_scam_rejected():
    assert scam_marker(_l("PS5", "je vends juste la boite, console non incluse")) is not None


def test_carrier_unlock_is_not_a_lock():
    assert scam_marker(_l("iPhone 12 desimlocke", "debloque tout operateur, comme neuf")) is None


def test_clean_listing_passes():
    ok, why = price_prefilter(_l("RTX 4070 comme neuve", "facture fournie"), 20, None, 1500)
    assert ok and why == "ok"


def test_exclude_drops_want_ad():
    ok, _ = text_prefilter(_l("Recherche ps5", "je cherche une console"), (), ("recherche", "je cherche"))
    assert not ok


def test_require_enforced():
    assert not text_prefilter(_l("PS5 console", ""), ("rtx",), ())[0]
    assert text_prefilter(_l("PC RTX 4070", ""), ("rtx",), ())[0]


def test_no_rules_passes():
    assert text_prefilter(_l("PS5", ""), (), ())[0]
