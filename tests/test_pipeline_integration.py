import datetime as dt
from pathlib import Path

from lbc.exceptions import DatadomeError

from techflip import pipeline as pipe
from techflip.config import SearchConfig, Settings
from techflip.domain import Listing


def _settings(tmp_path, searches, ai_url=""):
    # No owner sale ledger: these tests pin the market logic, not config/sold.yaml.
    return Settings(telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
                    ai_url=ai_url, sold_path="none.yaml", searches=searches)


def _listing(source_id, title, price, zipcode, desc, search_name, published_at=None):
    return Listing(
        source="leboncoin", source_id=source_id, url=f"https://lbc/{source_id}",
        title=title, price=price, description=desc,
        published_at=published_at or "2026-07-29T10:00:00",
        city="x", zipcode=zipcode, department="x", search_name=search_name,
    )


def _today_iso():
    """The resweep only revisits listings published in the last week."""
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class FakeSource:
    name = "leboncoin"

    def __init__(self, by_search):
        self.by_search = by_search

    def fetch(self, search, page=1):
        return self.by_search.get(search.name, []) if page == 1 else []


class FakeNotifier:
    enabled = True

    def __init__(self, delivers=True):
        self.deals = []
        self.delivers = delivers

    def send_deal(self, l, s, extra=()):
        self.deals.append((l, s, extra))
        return self.delivers

    def send_text(self, text):
        return self.delivers


def _pipe(tmp_path, monkeypatch, searches, by_search, ai_url=""):
    monkeypatch.setattr(pipe, "_make_source", lambda name, s: FakeSource(by_search))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(_settings(tmp_path, searches, ai_url))
    p.notifier = FakeNotifier()
    return p


def test_local_deal_alerts_far_thin_deal_does_not(tmp_path, monkeypatch):
    searches = (
        SearchConfig(name="PC Gamer", url="u", kind="hunt", min_price=150, max_price=1500),
        SearchConfig(name="PS5", url="u", kind="hunt", min_price=120, max_price=600),
    )
    local_pc = _listing("1", "PC Gamer RTX 4070 Ryzen 5 5600 16Go DDR4", 400,
                        "59000", "envoi possible", "PC Gamer")
    far_ps5 = _listing("2", "PS5 comme neuve", 380, "75001", "envoi possible", "PS5")
    local_ps5 = _listing("3", "PS5 edition disque", 250, "59000",
                         "remise en main propre", "PS5")
    p = _pipe(tmp_path, monkeypatch, searches, {"PC Gamer": [local_pc], "PS5": [far_ps5, local_ps5]})

    stats = p.run_once()

    alerted_ids = {l.source_id for l, _, _ in p.notifier.deals}
    assert "1" in alerted_ids       # local underpriced PC, RTX 4070 inside
    assert "3" in alerted_ids       # local PS5 well under value
    assert "2" not in alerted_ids   # far PS5 at market, shipping kills it
    assert stats["alerts"] == 2


def test_single_item_feeds_the_tracker(tmp_path, monkeypatch):
    ads = [_listing(str(i), "RTX 4070 Gigabyte", 300 + i, "59000", "envoi", "RTX 4070")
           for i in range(6)]
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="RTX 4070", url="u", kind="feeder"),),
              {"RTX 4070": ads})
    p.run_once()

    q = p.tracker.price("gpu:rtx-4070")
    assert q.source == "learned" and q.n == 6
    assert not p.notifier.deals  # feeder never alerts


def test_undelivered_alert_is_retried_not_burned(tmp_path, monkeypatch):
    """A deal may only be written off once it actually reached the phone.
    Telegram down used to still mark it 'confirmed', which is how a +214 EUR
    Steam Deck was silently never sent."""
    deal = _listing("9", "PS5 edition disque", 250, "59000",
                    "remise en main propre", "PS5", published_at=_today_iso())
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="PS5", url="u", kind="hunt",
                                                    min_price=120, max_price=600),), {"PS5": [deal]})
    p.notifier = FakeNotifier(delivers=False)
    p.run_once()
    assert p.notifier.deals                        # it tried
    assert p.store.alert_tier(deal.uid) != "confirmed"

    p.notifier = FakeNotifier(delivers=True)       # Telegram back up
    p.run_once()
    assert p.notifier.deals                        # retried instead of lost
    assert p.store.alert_tier(deal.uid) == "confirmed"


def test_games_and_accessories_do_not_teach_console_prices(tmp_path, monkeypatch):
    """Game and accessory ads kept teaching the tracker that a Switch costs
    25 EUR. Only a clean console ad may set a console price."""
    junk = [("Super Mario Odyssey - Switch game", 85),
            ("4 Nintendo switch spelletjes", 90),
            ("Housse de protection Nintendo Switch", 100),
            ("Manette pro Nintendo Switch", 95)]
    clean = [("Nintendo Switch", 150), ("Nintendo Switch", 155), ("Nintendo Switch", 160)]
    ads = [_listing(f"j{i}", t, px, "59000", "envoi", "Nintendo Switch") for i, (t, px) in enumerate(junk)]
    ads += [_listing(f"c{i}", t, px, "59000", "envoi", "Nintendo Switch") for i, (t, px) in enumerate(clean)]
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="Nintendo Switch", url="u", kind="feeder"),),
              {"Nintendo Switch": ads})
    p.run_once()

    assert sorted(p.store.component_prices("console:switch", "1970-01-01")) == [150, 155, 160]
    # Blended with the seed (3 < min_comparables), but off clean data: the
    # poisoned pool used to learn a median of 100 EUR for a Switch console.
    assert p.tracker.price("console:switch").unit_value == 157.0


def test_near_console_alerts_with_a_warning_when_the_ai_is_down(tmp_path, monkeypatch):
    """The vision model down must not silently swallow a near-home console
    deal: it alerts, flagged 'photo non vérifiée'. A confirmed mislabel still
    drops, for good."""
    real = _listing("A", "PS5 edition disque", 250, "59000", "remise en main propre", "PS5")
    fake_ps4 = _listing("B", "PS5 edition disque comme neuve", 250, "59000",
                        "remise en main propre", "PS5")
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="PS5", url="u", kind="hunt",
                                                    min_price=120, max_price=600),),
              {"PS5": [real, fake_ps4]}, ai_url="http://x")

    def fake_llm(l):
        if l.source_id == "B":                       # vision sees a PS4, not a PS5
            return {"type": "console", "condition": "bon", "is_trade": False, "risque_arnaque": 2,
                    "components": [{"type": "console", "model": "ps4 slim", "qty": 1}]}
        return None                                  # model unavailable (timeout)
    p.valuer.classify = fake_llm

    p.run_once()

    alerted = {l.source_id: extra for l, _, extra in p.notifier.deals}
    assert "A" in alerted
    assert any("non vérifiée" in line for line in alerted["A"])
    assert "B" not in alerted
    assert p.store.alert_tier("leboncoin:B") == "confirmed"      # discarded, never re-evaluated


def test_datadome_on_one_source_does_not_abort_the_others(tmp_path, monkeypatch):
    """A DataDome block on Leboncoin must not swallow the cycle: the 2ememain
    searches after it still run and can alert."""
    searches = (
        SearchConfig(name="PS5", source="leboncoin", url="u", kind="hunt", min_price=120, max_price=600),
        SearchConfig(name="PS5 bis", source="leboncoin", url="u", kind="hunt", min_price=120, max_price=600),
        SearchConfig(name="Steam Deck BE", source="2ememain", url="u", kind="hunt",
                     min_price=200, max_price=700),
    )
    deal = _listing("Z", "Valve Steam Deck OLED 512 Go", 395, "59000", "remise en main propre", "Steam Deck BE")

    class Blocked:
        name = "leboncoin"
        calls = 0

        def fetch(self, search, page=1):
            Blocked.calls += 1
            raise DatadomeError("blocked")

    monkeypatch.setattr(pipe, "_make_source",
                        lambda name, s: Blocked() if name == "leboncoin" else FakeSource({"Steam Deck BE": [deal]}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(_settings(tmp_path, searches))
    p.notifier = FakeNotifier()

    stats = p.run_once()

    assert "Z" in {l.source_id for l, _, _ in p.notifier.deals}   # 2ememain still ran
    assert stats["alerts"] == 1
    assert Blocked.calls == 1                                      # the blocked site was left alone


def test_ambiguous_console_does_not_fail_open_when_the_ai_is_down(tmp_path, monkeypatch):
    """A bare 'Nintendo Switch' is often a cheaper Lite: with the vision model
    down, no alert on the optimistic full-Switch value."""
    bare = _listing("A", "Nintendo Switch gris", 90, "59000", "remise en main propre", "Nintendo Switch")
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="Nintendo Switch", url="u", kind="hunt",
                                                    min_price=60, max_price=350),),
              {"Nintendo Switch": [bare]}, ai_url="http://x")
    p.valuer.classify = lambda l: None
    p.run_once()
    assert not p.notifier.deals


def test_no_ai_configured_still_fails_closed_on_an_ambiguous_console(tmp_path, monkeypatch):
    """Running without the vision model must behave like the model being down,
    not like the photo check not existing."""
    ad = _listing("1", "Nintendo Switch", 60, "59100", "bon etat", "Switch", published_at=_today_iso())
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="Switch", url="u", kind="hunt",
                                                    min_price=50, max_price=400),), {"Switch": [ad]})
    assert p.valuer.classify is None
    p.run_once()
    assert [l.title for l, _, _ in p.notifier.deals] == []


def test_no_ai_still_alerts_an_unambiguous_near_console_with_a_warning(tmp_path, monkeypatch):
    ad = _listing("1", "Xbox Series X", 150, "59100", "tres bon etat", "Xbox", published_at=_today_iso())
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="Xbox", url="u", kind="hunt",
                                                    min_price=50, max_price=600),), {"Xbox": [ad]})
    p.run_once()
    assert [l.title for l, _, _ in p.notifier.deals] == ["Xbox Series X"]
    assert any("photo non" in x for x in p.notifier.deals[0][2])


def test_whole_item_llm_estimate_for_unrecognized_local(tmp_path, monkeypatch):
    laptop = _listing("7", "PC Portable Gamer Legion 5i (mobile)", 400, "59000", "envoi possible", "Laptop")
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="Laptop", url="u", kind="hunt",
                                                    min_price=100, max_price=2000),),
              {"Laptop": [laptop]}, ai_url="http://x")
    p.valuer.classify = lambda l: {"valeur_revente_rapide": 700, "risque_arnaque": 1, "is_trade": False}

    p.run_once()

    assert len(p.notifier.deals) == 1
    _, sc, _ = p.notifier.deals[0]
    assert sc.true_value == 595.0 and sc.net_profit and sc.net_profit > 150


def test_a_wanted_ad_or_a_counterfeit_is_discarded_for_good(tmp_path, monkeypatch):
    """The scanner applies the same "not an offer" rules as the board."""
    ads = [_listing("w", "Recherche PS5 standard", 200, "59000", "", "PS5"),
           _listing("c", "PS5 copie", 150, "59000", "", "PS5")]
    p = _pipe(tmp_path, monkeypatch, (SearchConfig(name="PS5", url="u", kind="hunt",
                                                    min_price=100, max_price=600),), {"PS5": ads})
    p.run_once()
    assert not p.notifier.deals
    assert p.store.alert_tier("leboncoin:w") == p.store.alert_tier("leboncoin:c") == "confirmed"


def test_an_unreachable_site_is_tried_once_per_cycle(tmp_path, monkeypatch):
    """A refused connection is not retried on every search of that site."""
    searches = tuple(SearchConfig(name=f"s{i}", source="leboncoin", url="u", kind="hunt") for i in range(3))

    class Down:
        name = "leboncoin"
        calls = 0

        def fetch(self, search, page=1):
            Down.calls += 1
            raise ConnectionError("CONNECT tunnel failed, response 403")

    monkeypatch.setattr(pipe, "_make_source", lambda name, s: Down())
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(_settings(tmp_path, searches))
    p.notifier = FakeNotifier()
    assert p.run_once()["errors"] == 1 and Down.calls == 1
