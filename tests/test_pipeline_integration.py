import datetime as dt
from pathlib import Path

from lbc.exceptions import DatadomeError

from techflip import pipeline as pipe
from techflip.config import Settings, SearchConfig
from techflip.domain import Listing


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


def test_undelivered_alert_is_retried_not_burned(tmp_path, monkeypatch):
    """A deal may only be written off once it actually reached the phone.
    Telegram down (or a stubbed notifier) used to still mark it 'confirmed',
    which is how a +214 EUR Steam Deck was silently never sent."""
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=(SearchConfig(name="PS5", url="u", kind="hunt",
                                          min_price=120, max_price=600),),
    )
    deal = _listing("9", "PS5 edition disque", 250, "59000",
                    "remise en main propre", "PS5", published_at=_today_iso())
    monkeypatch.setattr(pipe, "_make_source", lambda name, s: FakeSource({"PS5": [deal]}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)

    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier(delivers=False)
    p.run_once()
    assert p.notifier.deals                        # it tried
    assert p.store.alert_tier(deal.uid) != "confirmed"

    p.notifier = FakeNotifier(delivers=True)       # Telegram back up
    p.run_once()
    assert p.notifier.deals                        # retried instead of lost
    assert p.store.alert_tier(deal.uid) == "confirmed"


def test_games_and_accessories_do_not_teach_console_prices(tmp_path, monkeypatch):
    """Real 2ememain pool: game and accessory ads kept teaching the tracker that
    a Switch costs 25 EUR. Only a clean console ad may set a console price."""
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=(SearchConfig(name="Nintendo Switch", url="u", kind="feeder"),),
    )
    # Priced inside the tracker's [0.5x, 2x] seed band, so the band guard alone
    # does not filter them out: they really do move the learned median.
    junk = [("Super Mario Odyssey - Switch game", 85),
            ("4 Nintendo switch spelletjes", 90),
            ("Housse de protection Nintendo Switch", 100),
            ("Manette pro Nintendo Switch", 95)]
    clean = [("Nintendo Switch", 150), ("Nintendo Switch", 155), ("Nintendo Switch", 160)]
    ads = [_listing(f"j{i}", t, px, "59000", "envoi", "Nintendo Switch")
           for i, (t, px) in enumerate(junk)]
    ads += [_listing(f"c{i}", t, px, "59000", "envoi", "Nintendo Switch")
            for i, (t, px) in enumerate(clean)]
    monkeypatch.setattr(pipe, "_make_source",
                        lambda name, s: FakeSource({"Nintendo Switch": ads}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()
    p.run_once()

    prices = sorted(p.store.component_prices("console:switch", "1970-01-01"))
    assert prices == [150, 155, 160]        # only real consoles taught a price
    # Blended with the seed (3 < min_comparables), but off clean data: the
    # poisoned pool used to learn a median of 100 EUR for a Switch console.
    assert p.tracker.price("console:switch").unit_value == 157.0


def test_easy_console_alerts_with_warning_when_llm_down(tmp_path, monkeypatch):
    """Ollama down/slow must not silently swallow a near-Lille console deal: it
    alerts, flagged 'photo non vérifiée'. A confirmed mislabel still drops."""
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="http://x",
        searches=(SearchConfig(name="PS5", url="u", kind="hunt",
                               min_price=120, max_price=600),),
    )
    real = _listing("A", "PS5 edition disque", 250, "59000",
                    "remise en main propre", "PS5")
    fake_ps4 = _listing("B", "PS5 edition disque comme neuve", 250, "59000",
                        "remise en main propre", "PS5")
    monkeypatch.setattr(pipe, "_make_source",
                        lambda name, s: FakeSource({"PS5": [real, fake_ps4]}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()

    def fake_llm(l):
        if l.source_id == "B":                       # vision sees a PS4, not a PS5
            return {"type": "console", "condition": "bon", "is_trade": False,
                    "risque_arnaque": 2,
                    "components": [{"type": "console", "model": "ps4 slim", "qty": 1}]}
        return None                                  # LLM unavailable (timeout)
    p._run_llm = fake_llm

    p.run_once()

    alerted = {l.source_id: extra for l, _, extra in p.notifier.deals}
    assert "A" in alerted                            # near Lille, alerts despite blind AI
    assert any("non vérifiée" in line for line in alerted["A"])
    assert "B" not in alerted                        # mislabel bait still dropped


def test_datadome_on_one_source_does_not_abort_the_others(tmp_path, monkeypatch):
    """A DataDome block on Leboncoin must not swallow the whole cycle: the
    reliable 2ememain searches after it still run and can alert."""
    searches = (
        SearchConfig(name="PS5", source="leboncoin", url="u", kind="hunt",
                     min_price=120, max_price=600),
        SearchConfig(name="Steam Deck BE", source="2ememain", url="u", kind="hunt",
                     min_price=200, max_price=700),
    )
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=searches,
    )
    deal = _listing("Z", "Valve Steam Deck OLED 512 Go", 395, "59000",
                    "remise en main propre", "Steam Deck BE")

    class Blocked:
        name = "leboncoin"

        def fetch(self, search, page=1):
            raise DatadomeError("blocked")

    def make(name, s):
        return Blocked() if name == "leboncoin" else FakeSource({"Steam Deck BE": [deal]})

    monkeypatch.setattr(pipe, "_make_source", make)
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()

    stats = p.run_once()

    assert "Z" in {l.source_id for l, _, _ in p.notifier.deals}   # 2ememain still ran
    assert stats["alerts"] == 1


def test_ambiguous_console_does_not_fail_open_when_llm_down(tmp_path, monkeypatch):
    """A bare 'Nintendo Switch' is often a cheaper Lite: with the vision model
    down we must not fire an alert on the optimistic full-Switch value. Contrast
    the unambiguous Steam Deck OLED, which does fail open (test above)."""
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="http://x",
        searches=(SearchConfig(name="Nintendo Switch", url="u", kind="hunt",
                               min_price=60, max_price=350),),
    )
    bare = _listing("A", "Nintendo Switch gris", 90, "59000",
                    "remise en main propre", "Nintendo Switch")
    monkeypatch.setattr(pipe, "_make_source",
                        lambda name, s: FakeSource({"Nintendo Switch": [bare]}))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()
    p._run_llm = lambda l: None                      # Ollama down

    p.run_once()

    assert not p.notifier.deals                      # no phantom deal on a maybe-Lite


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
    p._run_llm = lambda l: {"valeur_revente_rapide": 700, "risque_arnaque": 1, "is_trade": False}

    p.run_once()

    assert len(p.notifier.deals) == 1
    _, sc, _ = p.notifier.deals[0]
    assert sc.true_value == 595.0 and sc.net_profit and sc.net_profit > 150


def test_no_ai_configured_still_fails_closed_on_an_ambiguous_console(tmp_path, monkeypatch):
    """Running without the local vision model must behave like the model being
    down, not like the guard not existing.

    `if self.vetter and (needs_photo or ...)` skipped the whole block when no AI
    was configured, so `_verify_photo` never ran and the ambiguity guard was
    bypassed entirely. A bare "Nintendo Switch" -- which is very often the much
    cheaper Lite -- alerted at full console value. That matters now because the
    scanner is meant to run with the vision pass OFF: CPU inference on photos is
    what heats the laptop.
    """
    searches = (SearchConfig(name="Switch", url="u", kind="hunt",
                             min_price=50, max_price=400),)
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=searches,          # no vision model at all
    )
    # 8km from Lille: the EASY zone, where an unverified deal would otherwise
    # be allowed through with a warning.
    ad = _listing("1", "Nintendo Switch", 60, "59100", "bon etat", "Switch",
                  published_at=_today_iso())

    monkeypatch.setattr(pipe, "_make_source", lambda name, s: FakeSource({"Switch": [ad]}))
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()
    assert p.vetter is None
    p.run_once()

    titles = [l.title for l, _, _ in p.notifier.deals]
    assert titles == [], f"ambiguous console alerted with no photo check: {titles}"


def test_no_ai_still_alerts_an_unambiguous_local_console_with_a_warning(tmp_path, monkeypatch):
    """The counter-case: a model that cannot hide a cheaper sibling is still
    worth telling you about near Lille, flagged for you to eyeball on site."""
    searches = (SearchConfig(name="Xbox", url="u", kind="hunt",
                             min_price=50, max_price=600),)
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
        ai_url="", searches=searches,
    )
    ad = _listing("1", "Xbox Series X", 150, "59100", "tres bon etat", "Xbox",
                  published_at=_today_iso())

    monkeypatch.setattr(pipe, "_make_source", lambda name, s: FakeSource({"Xbox": [ad]}))
    p = pipe.Pipeline(settings)
    p.notifier = FakeNotifier()
    p.run_once()

    assert [l.title for l, _, _ in p.notifier.deals] == ["Xbox Series X"]
    extra = p.notifier.deals[0][2]
    assert any("photo non" in x for x in extra), extra
