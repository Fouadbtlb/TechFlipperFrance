"""Which ads may set a part's market price.

41 rows taught the tracker that an RTX 4070 card sells for 700 EUR: gaming
laptops whose title names the GPU and nothing else the catalog knows ("Lenovo
Legion Slim 5 16GB RAM Geforce RTX4070"), plus towers stored by the ingest
command, which had skipped the bundle guard. A 400 EUR card then showed +184.
"""
import datetime as dt

import pytest

from techflip.domain import Listing
from techflip.ingest import ingest
from techflip.pricing.catalog import load_catalog
from techflip.pricing.identify import teaching_key
from techflip.storage import Store

CATALOG = load_catalog("config/pricebook.yaml")


def _l(title, aisle=None, desc=""):
    return Listing(source="2ememain", source_id=title[:20], url="u", title=title,
                   price=500, published_at=dt.date.today().isoformat(),
                   description=desc, source_category=aisle)


@pytest.mark.parametrize("title", [
    "Lenovo Legion Slim 5 16GB RAM Geforce RTX4070",
    "HP Victus 16 | RTX 4070 | Ryzen 7 | 32 Go de mémoire DDR5",
    "Katana 15 RTX 4070 i7 16 Go DDR5 avec facture",
    "MSI Katana 17 B13VGK-833BE gaming laptop 17,3” RTX4070",
    "Dell XPS 16 9640 – Ultra 9 – 64 Go – RTX 4070",
    "ASUS ROG Strix G16 (2024) – i9-14900HX / RTX 4070 / 32GB RAM",
    "ASUS TUF Gaming A15 – Ryzen 9 – RTX 4070 – 16GB – 512GB",
    "Acer Nitro 17– Ryzen 9 / RTX 4070 / 32 Go / QHD 165 Hz",
    "Razer Blade 16 - RTX 4070 - I9 13th",
    "Yoga Pro 9i 16 (Ultra 9-Windows 11 Home-64GB-1TB-RTX 4070)",
    "Pc fixe rtx 4070 amd ryzen 7",
    "Pc RTX4070",
])
def test_machines_never_teach_a_card_price(title):
    assert teaching_key(_l(title), CATALOG) is None


@pytest.mark.parametrize("title", [
    "GeForce RTX 4070",
    "ZOTAC GAMING GeForce RTX 4070 Twin Edge 12GB GDDR6X Graphics",
    "MSI GeForce RTX 4070 Gaming X Slim White – 12 Go GDDR6X",
    "ASUS ROG Strix GeForce RTX 4070 OC",
    "ASUS TUF Gaming RTX 4070 12GB",
])
def test_cards_still_teach(title):
    assert teaching_key(_l(title, "cartes-video"), CATALOG) == "gpu:rtx-4070"


def test_a_sapphire_nitro_card_is_not_an_acer_nitro_laptop():
    key = teaching_key(_l("Sapphire Nitro+ RX 7800 XT 16GB"), CATALOG)
    assert key is not None and key.startswith("gpu:")


def test_a_phone_called_portable_still_teaches():
    key = teaching_key(_l("Téléphone portable Samsung Galaxy S24 128GB"), CATALOG)
    assert key is not None and key.startswith("phone:")


class _Src:
    def __init__(self, hits):
        self.hits = hits

    def fetch(self, s, page=1):
        return self.hits if page == 1 else []


def test_ingest_applies_the_same_rule(tmp_path):
    from techflip.config import SearchConfig
    store = Store(tmp_path / "t.db")
    hits = [_l("Pc gaming RTX 4070 Ryzen 7 5700X 32Go"), _l("GeForce RTX 4070")]
    s = SearchConfig(name="x", url="u", source="2ememain", min_price=1, max_price=5000)
    ingest(store, [s], {"2ememain": _Src(hits)}, catalog=CATALOG, sleep=0)
    rows = dict(store.conn.execute(
        "SELECT title, primary_component FROM listings").fetchall())
    assert rows["Pc gaming RTX 4070 Ryzen 7 5700X 32Go"] is None
    assert rows["GeForce RTX 4070"] == "gpu:rtx-4070"
