"""Dead links are how a deal tool loses the person using it, and a listing that
left the site is the only sold-side evidence there is. But a check that cannot
answer must never declare anything dead."""
from techflip import liveness
from techflip.domain import Listing
from techflip.liveness import query_for, verify
from techflip.sources.deuxememain import DeuxiemeMainSource
from techflip.storage import Store


def _l(uid, title, price=250):
    return Listing(source="2ememain", source_id=uid, url="u", title=title, price=price,
                   published_at="2026-08-01", description="", city="Menen",
                   lat=50.79, lng=3.12, search_name="PS5")


class _Source:
    name = "2ememain"

    def __init__(self, online=None, boom=False):
        self.online, self.boom, self.asked = online or {}, boom, []

    def is_online(self, row):
        self.asked.append(row["uid"])
        if self.boom:
            raise RuntimeError("DataDome")
        return self.online.get(row["source_id"])


def test_answers_are_recorded_and_only_a_no_marks_gone(tmp_path):
    store = Store(tmp_path / "t.db")
    for uid in ("m1", "m2", "m3"):
        store.upsert_listing(_l(uid, "Valve Steam Deck OLED 512 Go"))
    src = _Source({"m1": False, "m2": True, "m3": None})
    stats = verify(store, {"2ememain": src}, ["2ememain:m1", "2ememain:m2", "2ememain:m3"], pause=(0, 0))
    assert stats["results"] == {"2ememain:m1": "gone", "2ememain:m2": "alive", "2ememain:m3": "unknown"}
    assert store.get("2ememain:m1")["status"] == "gone"
    assert store.get("2ememain:m2")["status"] == "active"
    assert store.get("2ememain:m3")["status"] == "active"
    assert store.get("2ememain:m3")["last_checked"] is not None     # not re-picked every cycle


def test_going_missing_records_how_long_it_took_to_sell(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "Valve Steam Deck OLED 512 Go"))
    store.conn.execute("UPDATE listings SET first_seen = ?",
                       ("2026-08-01T00:00:00+00:00",))
    store.conn.commit()
    store.mark_gone("2ememain:m1", at="2026-08-07T00:00:00+00:00")
    row = store.get("2ememain:m1")
    assert row["status"] == "gone" and row["days_on_market"] == 6.0


def test_a_blocked_source_stops_and_declares_nothing_dead(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "Valve Steam Deck OLED 512 Go"))
    store.upsert_listing(_l("m2", "Nintendo Switch OLED"))
    src = _Source(boom=True)
    stats = verify(store, {"2ememain": src}, ["2ememain:m1", "2ememain:m2"], pause=(0, 0))
    assert stats["gone"] == 0 and stats["unknown"] == 2
    assert src.asked == ["2ememain:m1"]                       # stopped at the first failure
    assert store.get("2ememain:m1")["status"] == "active"


def test_a_listing_seen_again_comes_back(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_listing(_l("m1", "Valve Steam Deck OLED 512 Go"))
    store.mark_gone("2ememain:m1")
    store.upsert_listing(_l("m1", "Valve Steam Deck OLED 512 Go"))
    row = store.get("2ememain:m1")
    assert row["status"] == "active" and row["disappeared_at"] is None


def test_the_query_keeps_only_identifying_words():
    assert query_for("Valve Steam Deck OLED 512 Go") == "valve steam deck oled"
    assert query_for("PS5 en tres bon etat, a vendre urgent") == "ps5"
    assert query_for("Nintendo Switch OLED avec 3 jeux") == "nintendo switch oled jeux"


def test_a_blocked_2ememain_is_unknown_not_gone(monkeypatch):
    """2ememain answers a block with an empty, non-JSON page, not an error:
    read as "no results", every listing checked would be marked gone."""
    src = DeuxiemeMainSource()
    monkeypatch.setattr(src, "_search", lambda url, name: None)
    assert src.is_online({"title": "Valve Steam Deck OLED", "source_id": "1"}) is None
    monkeypatch.setattr(src, "_search", lambda url, name: [])
    assert src.is_online({"title": "Valve Steam Deck OLED", "source_id": "1"}) is None
    monkeypatch.setattr(src, "_search", lambda url, name: [_l("2", "Steam Deck")])
    assert src.is_online({"title": "Valve Steam Deck OLED", "source_id": "1"}) is False


def test_check_pauses_between_requests(monkeypatch, tmp_path):
    slept = []
    monkeypatch.setattr(liveness.time, "sleep", slept.append)
    store = Store(tmp_path / "t.db")
    for uid in ("a", "b"):
        store.upsert_listing(_l(uid, "Nintendo Switch OLED"))
    liveness.check(store, _Source({"a": True, "b": True}), [store.get("2ememain:a"), store.get("2ememain:b")])
    assert len(slept) == 1
