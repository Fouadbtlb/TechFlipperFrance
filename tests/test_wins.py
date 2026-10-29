"""Departed listings as sale evidence, price floor, crowd feedback, reposts,
reliable/à vérifier buckets, negotiation helper and the evening digest."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lbc.exceptions import DatadomeError

from techflip import liveness
from techflip import pipeline as pipe
from techflip.api.accounts import Accounts
from techflip.api.app import create_app
from techflip.api.deals import deals_for, negotiation
from techflip.api.fanout import PushFanout
from techflip.config import SearchConfig, Settings
from techflip.decision import default_policy
from techflip.domain import Listing
from techflip.geo import LILLE
from techflip.pricing.catalog import load_catalog
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store
from techflip.viewer import Viewer, judge
from tests.test_api import SECRET, FakePush, FakeRC, _api, _h, _paris, _push_user, _register, _seed_deal, _settings

CATALOG = load_catalog("config/pricebook.yaml")
NOW = datetime.now(timezone.utc)


def _single(store, i, price, key="gpu:rtx-4070", gone_days=None, seller=None, title=None):
    first = (NOW - timedelta(days=10)).isoformat()
    l = Listing(source="leboncoin", source_id=str(i), url="u", title=title or f"RTX 4070 n{i}", price=price,
                published_at=first, fetched_at=first, seller_id=seller, city="Lille")
    store.upsert_listing(l)
    store.set_primary_component(l.uid, key, True)
    if gone_days is not None:
        store.mark_gone(l.uid, at=(NOW - timedelta(days=10 - gone_days)).isoformat())
    return l.uid


def test_departed_listings_beat_asking_prices(tmp_path):
    s = Store(tmp_path / "t.db")
    for i, p in enumerate([520, 540, 560, 580, 600, 620]):        # still listed: asking
        _single(s, i, p)
    for i, p in enumerate([430, 440, 450, 460, 470], start=10):   # left the site
        _single(s, i, p, gone_days=3)
    q = PriceTracker(s, CATALOG, min_comparables=5).price("gpu:rtx-4070")
    assert q.source == "sold" and q.unit_value == 450 and q.n == 5
    assert q.days_to_sell == 3.0
    assert q.low is not None and q.low < q.unit_value


def test_floor_never_exceeds_value(tmp_path):
    from techflip.pricing.appraise import Item, appraise
    s = Store(tmp_path / "t.db")
    for i, p in enumerate([430, 440, 450, 460, 470]):
        _single(s, i, p, gone_days=2)
    a = appraise([Item("gpu:rtx-4070", 1, "working", "RTX 4070", "gpu")], PriceTracker(s, CATALOG), 0.85)
    assert a.floor_value is not None and a.floor_value <= a.true_value
    assert a.days_to_sell == 2.0


def test_crowd_correction_needs_several_people_and_is_bounded(tmp_path):
    s = Store(tmp_path / "t.db")
    uid = _single(s, 1, 480)
    for u in range(4):
        s.add_feedback(f"user{u}", uid, "high", None)
    since = (NOW - timedelta(days=90)).isoformat()
    assert s.feedback_factor("gpu:rtx-4070", since) == 1.0       # 4 voices: ignored
    s.add_feedback("user4", uid, "high", None)
    assert s.feedback_factor("gpu:rtx-4070", since) == 0.9       # unanimous "too high": -10 % max
    s.add_feedback("user4", uid, "fair", None)                    # changing a vote replaces it
    assert s.feedback_factor("gpu:rtx-4070", since) == pytest.approx(0.92)


def test_reported_resale_prices_count_as_sales(tmp_path):
    s = Store(tmp_path / "t.db")
    uids = [_single(s, i, 500) for i in range(5)]
    for i, u in enumerate(uids):
        s.add_feedback(f"user{i}", u, None, 455)
    q = PriceTracker(s, CATALOG, min_comparables=5).price("gpu:rtx-4070")
    assert q.source == "sold" and q.unit_value == 455


class _CheckingSource:
    name = "leboncoin"

    def __init__(self, gone_ids, block_after=None):
        self.gone_ids = set(gone_ids)
        self.calls = 0
        self.block_after = block_after

    def fetch(self, search, page=1):
        return []

    def is_online(self, row):
        self.calls += 1
        if self.block_after is not None and self.calls > self.block_after:
            raise DatadomeError("blocked")
        return row["source_id"] not in self.gone_ids


def _pipe(tmp_path, monkeypatch, src):
    settings = Settings(telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"), ai_url="",
                        searches=(SearchConfig(name="x", url="u"),), departure_checks=10)
    monkeypatch.setattr(pipe, "_make_source", lambda n, s: src)
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    monkeypatch.setattr(liveness.time, "sleep", lambda *a: None)
    return pipe.Pipeline(settings)


def test_departure_watcher_marks_gone_and_backs_off(tmp_path, monkeypatch):
    src = _CheckingSource(gone_ids={"1"})
    p = _pipe(tmp_path, monkeypatch, src)
    _single(p.store, 1, 450)
    _single(p.store, 2, 460)
    assert p._watch_departures() == 1
    gone = p.store.get("leboncoin:1")
    assert gone["status"] == "gone" and gone["days_on_market"] is not None
    assert p.store.get("leboncoin:2")["last_checked"] is not None
    assert p._watch_departures() == 0 and src.calls == 2          # nothing due again so soon

    blocked = _CheckingSource(gone_ids=set(), block_after=0)
    (tmp_path / "b").mkdir()
    p2 = _pipe(tmp_path / "b", monkeypatch, blocked)
    for i in range(3):
        _single(p2.store, i, 450)
    p2._watch_departures()
    assert blocked.calls == 1                                      # stops at the first block


def test_reposts_are_linked_and_shown_once(tmp_path):
    s = Store(tmp_path / "t.db")
    first = _seed_deal(tmp_path / "t.db", "a")
    s.conn.execute("UPDATE listings SET seller_id='s1', title='PS5 édition disque', title_key='ps5 edition disque', "
                   "first_seen=? WHERE uid=?", ((NOW - timedelta(days=5)).isoformat(), first))
    s.conn.commit()
    again = Listing(source="leboncoin", source_id="b", url="u", title="PS5 Edition Disque !", price=250,
                    published_at="2099-01-01", seller_id="s1", city="Lille", lat=LILLE[0], lng=LILLE[1])
    s.upsert_listing(again)
    row = s.get(again.uid)
    assert row["repost_of"] == first and row["reposts"] == 1
    s.save_appraisal(again.uid, true_value=400, price=250, confidence=0.9, category="console",
                     appraisal={"risk": 1, "shippable": True, "ship_class": "bulky"})
    v = Viewer(home=LILLE, policy=default_policy())
    shown = deals_for(s, v, 7)
    assert [r["uid"] for r, _ in shown] == [again.uid]
    n = negotiation(s.get(again.uid), judge(s.get(again.uid), v), v)
    assert n["leverage"] and n["opening"] < 250 <= n["max_price"]


def test_negotiation_never_offers_more_than_the_max():
    v = Viewer(home=LILLE, policy=default_policy())
    row = {"true_value": 300, "price": 260, "lat": LILLE[0], "lng": LILLE[1], "confidence": 0.9,
           "category": "console", "reposts": 0, "title": "PS5", "owner_type": None,
           "appraisal": '{"shippable": false, "ship_class": "bulky", "risk": 1}'}
    n = negotiation(row, judge(row, v), v)
    assert n["max_price"] == 270 and n["opening"] <= n["max_price"] and n["opening"] < 260
    assert "Bonjour" in n["message"] and "vous" in n["message"]


def test_buckets_and_feedback_endpoint(tmp_path):
    rc = FakeRC()
    settings = _settings(tmp_path)
    c = TestClient(create_app(settings, _api(), entitlements_http=rc.client()))
    solid = _seed_deal(settings.db_path, "1")
    shaky = _seed_deal(settings.db_path, "2")
    Store(settings.db_path).conn.execute("UPDATE listings SET confidence=0.1 WHERE uid=?", (shaky,)).connection.commit()
    tok = _register(c)
    assert c.post(f"/v1/deals/{solid}/feedback", headers=_h(tok), json={"verdict": "fair"}).status_code == 402
    rc.subs[tok["user_id"]] = None
    c.post("/v1/me/entitlement/sync", headers=_h(tok))
    c.patch("/v1/me/prefs", headers=_h(tok), json={"home_lat": LILLE[0], "home_lng": LILLE[1]})

    rel = c.get("/v1/deals", headers=_h(tok)).json()
    assert [d["uid"] for d in rel["items"]] == [solid] and rel["counts"] == {"reliable": 1, "check": 1}
    chk = c.get("/v1/deals?bucket=check", headers=_h(tok)).json()
    assert [d["uid"] for d in chk["items"]] == [shaky]

    r = c.post(f"/v1/deals/{solid}/feedback", headers=_h(tok), json={"verdict": "high"})
    assert r.json()["high"] == 1 and r.json()["mine"] == "high"
    bad = c.post(f"/v1/deals/{solid}/feedback", headers=_h(tok), json={"resale_price": 5000})
    assert bad.status_code == 400
    d = c.get(f"/v1/deals/{solid}", headers=_h(tok)).json()
    assert d["feedback"]["mine"] == "high" and d["negotiation"]["max_price"] > 0


def test_daily_digest_once_in_the_evening(tmp_path):
    settings = _settings(tmp_path)
    _seed_deal(settings.db_path, "1")
    _seed_deal(settings.db_path, "2")
    acc = Accounts(settings.db_path)
    u = _push_user(acc, "d1")
    acc.update_prefs(u, {"notify_mode": "daily"})
    push = FakePush()
    assert PushFanout(settings, push=push, clock=lambda: _paris(12))([]) == 0
    assert PushFanout(settings, push=push, clock=lambda: _paris(19))([]) == 1
    assert push.sent[0]["title"].startswith("Le relevé du jour : 2 affaires")
    _seed_deal(settings.db_path, "3")
    assert PushFanout(settings, push=push, clock=lambda: _paris(20))([]) == 0   # once a day


assert SECRET  # shared fixtures imported above


def test_unchecked_photos_never_count_as_reliable_and_shops_do_not_haggle():
    from techflip.api.deals import is_reliable
    v = Viewer(home=LILLE, policy=default_policy())
    row = {"true_value": 300, "price": 200, "lat": LILLE[0], "lng": LILLE[1], "confidence": 0.9,
           "category": "console", "reposts": 0, "title": "Xbox Series X", "owner_type": None,
           "appraisal": '{"shippable": false, "ship_class": "bulky", "risk": 1}'}
    assert is_reliable(row)
    assert not is_reliable({**row, "appraisal": '{"risk": 1, "photo_unverified": true}'})
    assert negotiation(row, judge(row, v), v) is not None
    assert negotiation({**row, "owner_type": "pro"}, judge(row, v), v) is None


def test_a_carrier_locked_phone_is_never_reliable():
    from techflip.api.deals import is_reliable
    row = {"true_value": 340, "price": 200, "lat": LILLE[0], "lng": LILLE[1], "confidence": 0.9,
           "category": "phone", "reposts": 0, "title": "Samsung S25 FE", "owner_type": "pro",
           "appraisal": '{"risk": null}'}
    assert is_reliable(row)
    assert not is_reliable({**row, "appraisal": '{"risk": null, "carrier_locked": true}'})


def test_the_card_says_why_a_deal_needs_checking():
    from techflip.api.deals import card
    v = Viewer(home=LILLE, policy=default_policy())
    row = {"uid": "cashconverters:1", "title": "Samsung S25 FE", "price": 200, "last_price": None,
           "true_value": 340, "lat": LILLE[0], "lng": LILLE[1], "confidence": 0.9, "category": "phone",
           "reposts": 0, "owner_type": "pro", "source": "cashconverters", "city": "Mouscron",
           "published_at": None, "first_seen": None, "raw_json": "{}",
           "appraisal": '{"risk": null, "carrier_locked": true}'}
    c = card(row, judge(row, v))
    assert c["shop"] and c["carrier_locked"] and not c["photo_unverified"]
