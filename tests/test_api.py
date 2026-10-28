import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from techflip.api.accounts import Accounts
from techflip.api.app import create_app
from techflip.api.attest import AppleAppAttest
from techflip.api.fanout import PushFanout
from techflip.config import ApiSettings, Settings
from techflip.domain import Listing
from techflip.geo import LILLE
from techflip.storage import Store
from tests.attest_fixtures import APP_ID, FakeApple, FakeDevice

SECRET = "x" * 40


class FakeRC:
    """RevenueCat v1 /subscribers stand-in. `subs[user_id] = expires ISO|None|'none'`."""

    def __init__(self):
        self.subs: dict[str, object] = {}
        self.calls = 0

    def handler(self, request: httpx.Request):
        self.calls += 1
        assert request.headers["Authorization"] == "Bearer sk_test"
        uid = request.url.path.rsplit("/", 1)[-1]
        ents = {}
        if uid in self.subs:
            ents["pro"] = {"expires_date": self.subs[uid], "grace_period_expires_date": None,
                           "product_identifier": "techflip_monthly"}
        return httpx.Response(200, json={"subscriber": {"entitlements": ents}})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _settings(tmp_path) -> Settings:
    return Settings(telegram_token="", telegram_chat_id="", db_path=Path(tmp_path / "t.db"),
                    ai_url="")


def _api(**over) -> ApiSettings:
    base = dict(jwt_secret=SECRET, attest_mode="off", revenuecat_secret_key="sk_test",
                revenuecat_webhook_auth="Bearer hook", list_calls_per_minute=1000)
    base.update(over)
    return ApiSettings(**base)


def _seed_deal(db, uid="1", price=250, value=400, lat=LILLE[0], lng=LILLE[1], cat="console"):
    s = Store(db)
    l = Listing(source="leboncoin", source_id=uid, url=f"https://lbc/{uid}", title=f"PS5 #{uid}",
                price=price, published_at="2099-01-01", city="Lille", lat=lat, lng=lng,
                image_urls=("https://img/1.jpg",))
    s.upsert_listing(l)
    s.save_appraisal(l.uid, true_value=value, price=price, confidence=0.9, category=cat,
                     appraisal={"method": "parts", "breakdown": [
                         {"key": "console:ps5", "label": "PS5", "qty": 1, "value": value,
                          "source": "learned", "n": 9}],
                         "risk": 1, "shippable": True, "ship_class": "bulky"})
    return l.uid


def _register(c) -> dict:
    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/register", json={"platform": "dev", "challenge": ch})
    assert r.status_code == 200, r.text
    return r.json()


def _h(tok):
    return {"Authorization": f"Bearer {tok['access_token']}"}


@pytest.fixture()
def env(tmp_path):
    rc = FakeRC()
    settings = _settings(tmp_path)
    app = create_app(settings, _api(), entitlements_http=rc.client())
    return TestClient(app), rc, settings


def test_paywall_blocks_until_revenuecat_says_paid(env):
    c, rc, settings = env
    uid = _seed_deal(settings.db_path)
    tok = _register(c)
    assert c.get("/v1/deals", headers=_h(tok)).status_code == 402
    assert c.get(f"/v1/deals/{uid}", headers=_h(tok)).status_code == 402
    me = c.get("/v1/me", headers=_h(tok)).json()
    assert me["entitlement"]["active"] is False

    # the user buys in the app; RevenueCat now knows; the app asks us to sync
    rc.subs[tok["user_id"]] = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    me = c.post("/v1/me/entitlement/sync", headers=_h(tok)).json()
    assert me["entitlement"]["active"] is True

    # needs a home before deals make sense
    assert c.get("/v1/deals", headers=_h(tok)).status_code == 409
    c.patch("/v1/me/prefs", headers=_h(tok), json={"home_lat": LILLE[0], "home_lng": LILLE[1]})
    feed = c.get("/v1/deals", headers=_h(tok)).json()
    assert feed["total"] == 1 and feed["items"][0]["net"] > 100
    d = c.get(f"/v1/deals/{uid}", headers=_h(tok)).json()
    assert d["url"] == "https://lbc/1" and d["parts"][0]["label"] == "PS5"


def test_client_cannot_self_grant(env):
    c, rc, _ = env
    tok = _register(c)
    # there is no endpoint that accepts an entitlement from the client
    r = c.patch("/v1/me/prefs", headers=_h(tok), json={"entitled_until": "2999-01-01"})
    assert r.status_code == 200
    assert c.get("/v1/deals", headers=_h(tok)).status_code == 402


def test_expired_subscription_loses_access_and_lifetime_keeps_it(env):
    c, rc, _ = env
    tok = _register(c)
    rc.subs[tok["user_id"]] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert c.post("/v1/me/entitlement/sync", headers=_h(tok)).json()["entitlement"]["active"] is False
    rc.subs[tok["user_id"]] = None   # lifetime purchase
    assert c.post("/v1/me/entitlement/sync", headers=_h(tok)).json()["entitlement"]["active"] is True


def test_webhook_requires_secret_and_resyncs(env):
    c, rc, _ = env
    tok = _register(c)
    body = {"event": {"type": "INITIAL_PURCHASE", "app_user_id": tok["user_id"],
                      "aliases": ["$RCAnonymousID:abc"]}}
    assert c.post("/v1/webhooks/revenuecat", json=body).status_code == 401
    assert c.post("/v1/webhooks/revenuecat", json=body,
                  headers={"Authorization": "Bearer nope"}).status_code == 401
    rc.subs[tok["user_id"]] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    r = c.post("/v1/webhooks/revenuecat", json=body, headers={"Authorization": "Bearer hook"})
    assert r.json()["synced"] == 1
    assert c.get("/v1/me", headers=_h(tok)).json()["entitlement"]["active"] is True


def test_refresh_rotates_and_reuse_revokes_session(env):
    c, _, _ = env
    tok = _register(c)
    ch = c.post("/v1/auth/challenge").json()["challenge"]
    new = c.post("/v1/auth/refresh", json={"refresh_token": tok["refresh_token"], "challenge": ch})
    assert new.status_code == 200
    new = new.json()
    # the old refresh token is replayed (stolen copy): the whole family dies
    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/refresh", json={"refresh_token": tok["refresh_token"], "challenge": ch})
    assert r.json()["detail"]["code"] == "session_revoked"
    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/refresh", json={"refresh_token": new["refresh_token"], "challenge": ch})
    assert r.status_code == 401


def test_challenge_is_single_use_and_tokens_are_checked(env):
    c, _, _ = env
    ch = c.post("/v1/auth/challenge").json()["challenge"]
    assert c.post("/v1/auth/register", json={"platform": "dev", "challenge": ch}).status_code == 200
    assert c.post("/v1/auth/register", json={"platform": "dev", "challenge": ch}).status_code == 401
    assert c.get("/v1/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    import jwt as pyjwt
    forged = pyjwt.encode({"sub": "x", "did": "y", "typ": "access", "iss": "techflip",
                           "exp": 9999999999}, "wrong-secret-" * 4, algorithm="HS256")
    assert c.get("/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_far_viewer_sees_different_deals(env):
    c, rc, settings = env
    _seed_deal(settings.db_path, "near", price=300, value=400)
    tok = _register(c)
    rc.subs[tok["user_id"]] = None
    c.post("/v1/me/entitlement/sync", headers=_h(tok))
    c.patch("/v1/me/prefs", headers=_h(tok), json={"home_lat": 43.30, "home_lng": 5.38,
                                                   "radius_km": 50})  # Marseille
    assert c.get("/v1/deals", headers=_h(tok)).json()["total"] == 0  # shipping eats it


def test_teaser_reveals_nothing_actionable(env):
    c, _, settings = env
    _seed_deal(settings.db_path)
    tok = _register(c)
    c.patch("/v1/me/prefs", headers=_h(tok), json={"home_lat": LILLE[0], "home_lng": LILLE[1]})
    t = c.get("/v1/teaser", headers=_h(tok)).json()
    assert t["count"] == 1 and t["best_net"] % 10 == 0
    assert "url" not in json.dumps(t) and "PS5" not in json.dumps(t)


def test_sold_reports_and_daily_ceiling(tmp_path):
    rc = FakeRC()
    settings = _settings(tmp_path)
    c = TestClient(create_app(settings, _api(detail_views_per_day=2), entitlements_http=rc.client()))
    uid = _seed_deal(settings.db_path)
    toks = []
    for _ in range(2):
        t = _register(c)
        rc.subs[t["user_id"]] = None
        c.post("/v1/me/entitlement/sync", headers=_h(t))
        c.patch("/v1/me/prefs", headers=_h(t), json={"home_lat": LILLE[0], "home_lng": LILLE[1]})
        toks.append(t)
    assert c.get(f"/v1/deals/{uid}", headers=_h(toks[0])).status_code == 200
    assert c.get(f"/v1/deals/{uid}", headers=_h(toks[0])).status_code == 200
    assert c.get(f"/v1/deals/{uid}", headers=_h(toks[0])).status_code == 429
    for t in toks:
        c.post(f"/v1/hidden/{uid}", headers=_h(t), json={"reason": "sold"})
    assert Store(settings.db_path).get(uid)["status"] == "gone"


def test_enforced_ios_attestation_end_to_end(tmp_path):
    apple = FakeApple()
    rc = FakeRC()
    settings = _settings(tmp_path)
    app = create_app(settings, _api(attest_mode="enforce"),
                     apple=AppleAppAttest(APP_ID, apple.root_pem), entitlements_http=rc.client())
    c = TestClient(app)
    dev = FakeDevice(apple)

    ch = c.post("/v1/auth/challenge").json()["challenge"]
    assert c.post("/v1/auth/register", json={"platform": "dev", "challenge": ch}).status_code == 400

    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/register", json={"platform": "ios", "challenge": ch,
                                         "key_id": dev.key_id, "attestation": dev.attest(ch)})
    assert r.status_code == 200, r.text
    tok = r.json()

    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/refresh", json={"refresh_token": tok["refresh_token"], "challenge": ch})
    assert r.status_code == 400   # no device proof, no new token

    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/refresh", json={"refresh_token": tok["refresh_token"], "challenge": ch,
                                        "assertion": dev.assert_(ch)})
    assert r.status_code == 200, r.text

    # a script that stole the refresh token but not the Secure Enclave key
    thief = FakeDevice(apple)
    ch = c.post("/v1/auth/challenge").json()["challenge"]
    r = c.post("/v1/auth/refresh", json={"refresh_token": r.json()["refresh_token"],
                                        "challenge": ch, "assertion": thief.assert_(ch)})
    assert r.json()["detail"]["code"] == "attestation_failed"


def test_dev_unlock_refused_in_enforce_mode(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_settings(tmp_path), _api(attest_mode="enforce"), dev_unlock_all=True)


class FakePush:
    def __init__(self):
        self.sent = []

    def send(self, messages):
        self.sent += messages
        return []


def test_push_fanout_once_per_user_and_deal(tmp_path):
    settings = _settings(tmp_path)
    uid = _seed_deal(settings.db_path)
    acc = Accounts(settings.db_path)
    paid = acc.create_user("dev", "d1")
    acc.update_prefs(paid, {"home_lat": LILLE[0], "home_lng": LILLE[1]})
    acc.set_push_token(paid, "ExponentPushToken[abc]")
    acc.set_entitlement(paid, datetime.now(timezone.utc) + timedelta(days=3), "m")
    free = acc.create_user("dev", "d2")
    acc.update_prefs(free, {"home_lat": LILLE[0], "home_lng": LILLE[1]})
    acc.set_push_token(free, "ExponentPushToken[def]")

    push = FakePush()
    fan = PushFanout(settings, push=push)
    assert fan([uid]) == 1
    assert push.sent[0]["to"] == "ExponentPushToken[abc]" and push.sent[0]["data"]["uid"] == uid
    assert fan([uid]) == 0   # never twice
