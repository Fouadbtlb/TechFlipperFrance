import json
from pathlib import Path

from techflip import pipeline as pipe
from techflip.config import SearchConfig, Settings
from techflip.decision import default_policy
from techflip.domain import Listing
from techflip.geo import LILLE
from techflip.storage import Store
from techflip.viewer import Viewer, judge, policy_for

PARIS = (48.86, 2.34)


def _row(price=250, true_value=400, lat=LILLE[0], lng=LILLE[1], shippable=True,
         category="console", risk=None, confidence=0.8):
    return {
        "price": price, "true_value": true_value, "lat": lat, "lng": lng,
        "confidence": confidence, "category": category,
        "appraisal": json.dumps({"shippable": shippable, "ship_class": "bulky", "risk": risk}),
    }


def test_same_listing_is_a_deal_near_and_not_far():
    near = Viewer(home=LILLE, policy=default_policy())
    far = Viewer(home=PARIS, policy=default_policy())
    row = _row(price=300, true_value=400, shippable=False)
    assert judge(row, near).alert
    jf = judge(row, far)
    assert not jf.alert and jf.decision.zone == "HARD"


def test_radius_hides_far_pickup_but_shipping_keeps_it_visible():
    v = Viewer(home=PARIS, policy=default_policy(), radius_km=50, include_shipping=False)
    assert not judge(_row(shippable=True), v).visible
    v2 = Viewer(home=PARIS, policy=default_policy(), radius_km=50, include_shipping=True)
    j = judge(_row(shippable=True), v2)
    assert j.visible and j.mode == "ship" and j.logistics == 25.0


def test_category_filter():
    v = Viewer(home=LILLE, policy=default_policy(), categories=frozenset({"gpu"}))
    assert not judge(_row(category="console"), v).visible


def test_personal_min_profit_raises_near_bar_only_upward_far():
    p = policy_for(50, default_policy())
    assert p.bars == {"EASY": 50.0, "MEDIUM": 80.0, "HARD": 120.0}
    low = policy_for(10, default_policy())
    assert low.bars["EASY"] == 10.0 and low.bars["HARD"] == 120.0


def test_price_drop_is_recorded(tmp_path):
    s = Store(tmp_path / "t.db")
    base = dict(source="leboncoin", source_id="1", url="u", title="PS5", published_at="x")
    assert s.upsert_listing(Listing(price=400, **base)) is True
    assert s.upsert_listing(Listing(price=350, **base)) is False
    row = s.get("leboncoin:1")
    assert row["price"] == 350 and row["last_price"] == 400
    assert [p["price"] for p in s.price_points("leboncoin:1")] == [400, 350]
    s.upsert_listing(Listing(price=350, **base))  # unchanged: no new point
    assert len(s.price_points("leboncoin:1")) == 2


class _Src:
    name = "leboncoin"

    def __init__(self, ads):
        self.ads = ads

    def fetch(self, search, page=1):
        return self.ads if page == 1 else []


class _Notifier:
    enabled = False

    def send_deal(self, *a):
        pass

    def send_text(self, *a):
        pass


def test_llm_verdict_is_cached_across_resweeps_and_fanout_gets_deals(tmp_path, monkeypatch):
    settings = Settings(
        telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"), ai_url="http://x",
        searches=(SearchConfig(name="PS5", url="u", kind="hunt", min_price=100, max_price=900),),
    )
    ad = Listing(source="leboncoin", source_id="9", url="u", title="PS5 edition disque",
                 price=290, published_at="2099-01-01T00:00:00", zipcode="75001",
                 description="envoi possible", search_name="PS5")
    monkeypatch.setattr(pipe, "_make_source", lambda n, s: _Src([ad]))
    monkeypatch.setattr(pipe.time, "sleep", lambda *a: None)
    fanned = []
    p = pipe.Pipeline(settings, fanout=fanned.extend)
    p.notifier = _Notifier()
    calls = []

    def fake_llm(l):
        calls.append(l.uid)
        return {"components": [{"type": "console", "model": "PS5", "qty": 1}],
                "risque_arnaque": 1, "is_trade": False}

    p._run_llm = fake_llm
    p.run_once()
    p.run_once()
    assert calls == ["leboncoin:9"]           # second cycle reused the cached verdict
    row = p.store.get("leboncoin:9")
    assert row["appraisal"] and row["category"] == "console"
    assert row["lat"] is not None              # pinned from its postcode
    assert fanned == ["leboncoin:9", "leboncoin:9"]  # positive margin fanned out each cycle


def test_unreachable_postal_db_does_not_crash(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "pgeocode":
            raise OSError("download blocked")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    from techflip.geo import Locator
    assert Locator().distance_to_lille("62000") is not None   # anchor table
