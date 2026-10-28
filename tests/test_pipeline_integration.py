from pathlib import Path

from techflip import pipeline as pipe
from techflip.config import SearchConfig, Settings
from techflip.domain import Listing


def _listing(source_id, title, price, zipcode, desc, search_name):
    return Listing(
        source="leboncoin", source_id=source_id, url=f"https://lbc/{source_id}",
        title=title, price=price, published_at="2026-07-29T10:00:00", description=desc,
        city="x", zipcode=zipcode, department="x", search_name=search_name,
    )


class FakeSource:
    name = "leboncoin"

    def __init__(self, by_search):
        self.by_search = by_search

    def fetch(self, search, page=1):
        return self.by_search.get(search.name, []) if page == 1 else []


class FakeNotifier:
    enabled = True

    def __init__(self):
        self.deals = []

    def send_deal(self, l, s, extra=()):
        self.deals.append((l, s, extra))

    def send_text(self, text):
        pass


def test_local_deal_alerts_far_thin_deal_does_not(tmp_path, monkeypatch):
    searches = (
        SearchConfig(name="PC Gamer", url="u", kind="hunt", min_price=150, max_price=1500),
        SearchConfig(name="PS5", url="u", kind="hunt", min_price=120, max_price=600),
    )
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=searches,
    )

    local_pc = _listing("1", "PC Gamer RTX 4070 Ryzen 5 5600 16Go DDR4", 400,
                        "59000", "envoi possible", "PC Gamer")
    far_ps5 = _listing("2", "PS5 comme neuve", 380, "75001", "envoi possible", "PS5")
    local_ps5 = _listing("3", "PS5 edition disque", 250, "59000",
                         "remise en main propre", "PS5")
    fake = FakeSource({"PC Gamer": [local_pc], "PS5": [far_ps5, local_ps5]})

    monkeypatch.setattr(pipe, "_make_source", lambda name, s: fake)
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()

    stats = p.run_once()

    alerted_ids = {l.source_id for l, _, _ in p.notifier.deals}
    assert "1" in alerted_ids       # local underpriced PC, RTX 4070 inside
    assert "3" in alerted_ids       # local PS5 well under value
    assert "2" not in alerted_ids   # far PS5 at market, shipping kills it
    assert stats["alerts"] == 2


def test_single_item_feeds_the_tracker(tmp_path, monkeypatch):
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=(SearchConfig(name="RTX 4070", url="u", kind="feeder"),),
    )
    ads = [_listing(str(i), "RTX 4070 Gigabyte", 300 + i, "59000", "envoi", "RTX 4070")
           for i in range(6)]
    monkeypatch.setattr(pipe, "_make_source", lambda name, s: FakeSource({"RTX 4070": ads}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()
    p.run_once()

    q = p.tracker.price("gpu:rtx-4070")
    assert q.source == "learned" and q.n == 6
    assert not p.notifier.deals  # feeder never alerts


def test_whole_item_llm_estimate_for_unrecognized_local(tmp_path, monkeypatch):
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="http://x",
        searches=(SearchConfig(name="Laptop", url="u", kind="hunt",
                               min_price=100, max_price=2000),),
    )
    laptop = _listing("7", "PC Portable Gamer Legion 5i (mobile)", 400,
                      "59000", "envoi possible", "Laptop")
    monkeypatch.setattr(pipe, "_make_source", lambda name, s: FakeSource({"Laptop": [laptop]}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()
    p.valuer.classify = lambda l: {"valeur_revente_rapide": 700, "risque_arnaque": 1, "is_trade": False}

    p.run_once()

    assert len(p.notifier.deals) == 1
    _, sc, _ = p.notifier.deals[0]
    assert sc.true_value == 595.0 and sc.net_profit and sc.net_profit > 150
