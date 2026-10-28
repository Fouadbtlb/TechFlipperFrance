import pytest
from cryptography.hazmat.primitives import serialization

from techflip.api.attest import AAGUID_DEV, AppleAppAttest, AttestationError, check_play_verdict
from tests.attest_fixtures import APP_ID, FakeApple, FakeDevice


@pytest.fixture()
def apple():
    return FakeApple()


def test_valid_attestation_then_assertions(apple):
    v = AppleAppAttest(APP_ID, apple.root_pem)
    dev = FakeDevice(apple)
    key = v.verify_attestation(dev.key_id, dev.attest("chal-1"), "chal-1")
    assert key.counter == 0 and key.key_id == dev.key_id
    c1 = v.verify_assertion(dev.assert_("chal-2"), "chal-2", key.public_key_der, 0)
    c2 = v.verify_assertion(dev.assert_("chal-3"), "chal-3", key.public_key_der, c1)
    assert c2 > c1


def test_attestation_rejects_wrong_challenge(apple):
    v = AppleAppAttest(APP_ID, apple.root_pem)
    dev = FakeDevice(apple)
    with pytest.raises(AttestationError, match="nonce"):
        v.verify_attestation(dev.key_id, dev.attest("issued"), "other")


def test_attestation_rejects_foreign_root(apple):
    v = AppleAppAttest(APP_ID, FakeApple().root_pem)  # a different "Apple"
    dev = FakeDevice(apple)
    with pytest.raises(AttestationError, match="chain"):
        v.verify_attestation(dev.key_id, dev.attest("c"), "c")


def test_attestation_rejects_other_app_and_wrong_env(apple):
    dev = FakeDevice(apple, app_id="ABCDE12345.com.cracked.clone")
    with pytest.raises(AttestationError, match="another app"):
        AppleAppAttest(APP_ID, apple.root_pem).verify_attestation(dev.key_id, dev.attest("c"), "c")
    devdev = FakeDevice(apple, aaguid=AAGUID_DEV)
    with pytest.raises(AttestationError, match="environment"):
        AppleAppAttest(APP_ID, apple.root_pem).verify_attestation(
            devdev.key_id, devdev.attest("c"), "c")


def test_attestation_rejects_key_id_swap(apple):
    v = AppleAppAttest(APP_ID, apple.root_pem)
    a, b = FakeDevice(apple), FakeDevice(apple)
    with pytest.raises(AttestationError, match="key id"):
        v.verify_attestation(b.key_id, a.attest("c"), "c")


def test_assertion_replay_and_forgery(apple):
    v = AppleAppAttest(APP_ID, apple.root_pem)
    dev = FakeDevice(apple)
    key = v.verify_attestation(dev.key_id, dev.attest("c"), "c")
    a = dev.assert_("x")
    v.verify_assertion(a, "x", key.public_key_der, 0)
    with pytest.raises(AttestationError, match="counter"):
        v.verify_assertion(a, "x", key.public_key_der, 1)         # replayed
    with pytest.raises(AttestationError, match="signature"):
        v.verify_assertion(dev.assert_("x"), "y", key.public_key_der, 1)  # other challenge
    other = FakeDevice(apple)
    other_pub = other.key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(AttestationError, match="signature"):
        v.verify_assertion(dev.assert_("z"), "z", other_pub, 0)    # cloned key id


def _verdict(**over):
    p = {
        "requestDetails": {"requestPackageName": "fr.techflip.app", "requestHash": "chal",
                           "timestampMillis": "1000000"},
        "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED", "packageName": "fr.techflip.app"},
        "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
        "accountDetails": {"appLicensingVerdict": "LICENSED"},
    }
    for k, v in over.items():
        p[k] = v
    return p


def _check(p, h="chal", now=1000000 + 1000):
    check_play_verdict(p, "fr.techflip.app", h, True, now, 300000)


def test_play_verdict_ok():
    _check(_verdict())


@pytest.mark.parametrize("over,match", [
    ({"appIntegrity": {"appRecognitionVerdict": "UNRECOGNIZED_VERSION",
                       "packageName": "fr.techflip.app"}}, "modified"),
    ({"deviceIntegrity": {}}, "rooted"),
    ({"accountDetails": {"appLicensingVerdict": "UNLICENSED"}}, "Play"),
])
def test_play_verdict_rejects_tampering(over, match):
    with pytest.raises(AttestationError, match=match):
        _check(_verdict(**over))


def test_play_verdict_bound_to_challenge_and_fresh():
    with pytest.raises(AttestationError, match="challenge"):
        _check(_verdict(), h="other")
    with pytest.raises(AttestationError, match="old"):
        _check(_verdict(), now=1000000 + 10 * 60 * 1000)
