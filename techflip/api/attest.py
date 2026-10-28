"""Device attestation: prove a request comes from OUR untampered app on a real
device, not from a script, an emulator farm, or a repackaged/cracked APK/IPA.

- iOS: App Attest (DeviceCheck). The app makes a Secure Enclave key, Apple
  certifies it is bound to our App ID, and every later proof is a signature
  from that key with a strictly increasing counter (no replay, no cloning).
- Android: Play Integrity (Standard API). Google signs a verdict saying the
  binary is the one Play distributed, on a certified device, installed from
  Play. We decode it server-side with a service account.

Both bind to a single-use server challenge, so a captured proof is worthless.
The verification is pure (inputs in, verdict out) apart from the Play decode
HTTP call, which is injectable for tests.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import cbor2
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

NONCE_OID = x509.ObjectIdentifier("1.2.840.113635.100.8.2")
AAGUID_PROD = b"appattest" + b"\x00" * 7
AAGUID_DEV = b"appattestdevelop"


class AttestationError(Exception):
    pass


def _b64(s: str | bytes) -> bytes:
    if isinstance(s, bytes):
        s = s.decode()
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


@dataclass(frozen=True)
class AttestedKey:
    key_id: str            # base64 key id as the app reports it
    public_key_der: bytes  # SubjectPublicKeyInfo, stored per device
    counter: int
    receipt: bytes         # for Apple's fraud-metric service, optional use


class AppleAppAttest:
    def __init__(self, app_id: str, root_ca_pem: bytes, environment: str = "production"):
        if not app_id or "." not in app_id:
            raise ValueError("IOS_APP_ID must be TEAMID.bundle.id")
        self.rp_id_hash = _sha256(app_id.encode())
        self.root = x509.load_pem_x509_certificate(root_ca_pem)
        self.aaguid = AAGUID_DEV if environment == "development" else AAGUID_PROD

    # --- one-time key registration ---

    def verify_attestation(self, key_id_b64: str, attestation_b64: str, challenge: str,
                           now: datetime | None = None) -> AttestedKey:
        try:
            obj = cbor2.loads(_b64(attestation_b64))
            fmt = obj["fmt"]
            x5c = obj["attStmt"]["x5c"]
            receipt = obj["attStmt"].get("receipt", b"")
            auth_data = obj["authData"]
        except Exception as e:
            raise AttestationError(f"malformed attestation: {e}") from e
        if fmt != "apple-appattest" or len(x5c) < 2:
            raise AttestationError("not an App Attest statement")

        cred = x509.load_der_x509_certificate(x5c[0])
        inter = x509.load_der_x509_certificate(x5c[1])
        # 1. chain: credCert <- intermediate <- Apple App Attestation Root
        _check_chain([cred, inter], self.root, now)

        # 2-4. nonce = SHA256(authData || SHA256(challenge)) sits in credCert
        nonce = _sha256(auth_data + _sha256(challenge.encode()))
        if not hmac.compare_digest(_cert_nonce(cred), nonce):
            raise AttestationError("nonce mismatch (stale or forged challenge)")

        # 5. key id is SHA256 of the credential's uncompressed EC point
        pub = cred.public_key()
        if not isinstance(pub, ec.EllipticCurvePublicKey):
            raise AttestationError("credential key is not EC")
        point = pub.public_bytes(serialization.Encoding.X962,
                                 serialization.PublicFormat.UncompressedPoint)
        key_id = _b64(key_id_b64)
        if not hmac.compare_digest(_sha256(point), key_id):
            raise AttestationError("key id does not match credential")

        rp_id_hash, counter, aaguid, cred_id = _parse_auth_data(auth_data, attested=True)
        # 6. bound to our App ID
        if not hmac.compare_digest(rp_id_hash, self.rp_id_hash):
            raise AttestationError("attestation is for another app")
        # 7. fresh key
        if counter != 0:
            raise AttestationError("counter must be 0 at attestation")
        # 8. production vs development environment
        if aaguid != self.aaguid:
            raise AttestationError("wrong App Attest environment")
        # 9. credential id is the key id
        if not hmac.compare_digest(cred_id, key_id):
            raise AttestationError("credential id mismatch")

        der = pub.public_bytes(serialization.Encoding.DER,
                               serialization.PublicFormat.SubjectPublicKeyInfo)
        return AttestedKey(key_id_b64, der, 0, receipt)

    # --- every later proof ---

    def verify_assertion(self, assertion_b64: str, client_data: str, public_key_der: bytes,
                         prev_counter: int) -> int:
        """Returns the new counter; the caller must persist it."""
        try:
            obj = cbor2.loads(_b64(assertion_b64))
            signature = obj["signature"]
            auth_data = obj["authenticatorData"]
        except Exception as e:
            raise AttestationError(f"malformed assertion: {e}") from e
        nonce = _sha256(auth_data + _sha256(client_data.encode()))
        pub = serialization.load_der_public_key(public_key_der)
        try:
            pub.verify(signature, nonce, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as e:
            raise AttestationError("bad assertion signature") from e
        rp_id_hash, counter, _, _ = _parse_auth_data(auth_data, attested=False)
        if not hmac.compare_digest(rp_id_hash, self.rp_id_hash):
            raise AttestationError("assertion is for another app")
        if counter <= prev_counter:
            raise AttestationError("counter did not increase (replay or cloned key)")
        return counter


def _check_chain(chain: list[x509.Certificate], root: x509.Certificate,
                 now: datetime | None) -> None:
    now = now or datetime.now(timezone.utc)
    issuers = chain[1:] + [root]
    for cert, issuer in zip(chain, issuers):
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise AttestationError("certificate expired or not yet valid")
        try:
            cert.verify_directly_issued_by(issuer)
        except (ValueError, TypeError, InvalidSignature) as e:
            raise AttestationError("certificate chain does not reach Apple's root") from e


def _cert_nonce(cert: x509.Certificate) -> bytes:
    try:
        ext = cert.extensions.get_extension_for_oid(NONCE_OID).value
    except x509.ExtensionNotFound as e:
        raise AttestationError("missing App Attest nonce extension") from e
    der = ext.value  # SEQUENCE { [1] EXPLICIT OCTET STRING nonce }
    tag, body, _ = _der(der, 0)
    if tag != 0x30:
        raise AttestationError("bad nonce extension")
    i = 0
    while i < len(body):
        tag, inner, i = _der(body, i)
        if tag == 0xA1:
            t2, octets, _ = _der(inner, 0)
            if t2 == 0x04:
                return octets
    raise AttestationError("nonce not found in extension")


def _der(buf: bytes, i: int) -> tuple[int, bytes, int]:
    """Minimal DER TLV reader: (tag, value, next_index)."""
    tag = buf[i]
    length = buf[i + 1]
    i += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(buf[i:i + n], "big")
        i += n
    return tag, buf[i:i + length], i + length


def _parse_auth_data(ad: bytes, attested: bool):
    if len(ad) < 37:
        raise AttestationError("authenticator data too short")
    rp_id_hash = ad[:32]
    counter = int.from_bytes(ad[33:37], "big")
    if not attested:
        return rp_id_hash, counter, None, None
    if len(ad) < 55:
        raise AttestationError("missing attested credential data")
    aaguid = ad[37:53]
    cred_len = int.from_bytes(ad[53:55], "big")
    cred_id = ad[55:55 + cred_len]
    return rp_id_hash, counter, aaguid, cred_id


# ---------------------------------------------------------------- Android


class PlayIntegrity:
    """Standard Integrity API verdict check. `decode` is token -> payload dict
    (tokenPayloadExternal); the default calls Google with a service account."""

    MAX_AGE_MS = 5 * 60 * 1000

    def __init__(self, package: str, service_account_json: str = "",
                 require_licensed: bool = True, decode=None):
        if not package:
            raise ValueError("ANDROID_PACKAGE must be set")
        self.package = package
        self.require_licensed = require_licensed
        self._decode = decode or _google_decoder(package, service_account_json)

    def verify(self, token: str, request_hash: str, now_ms: int | None = None) -> dict:
        payload = self._decode(token)
        check_play_verdict(payload, self.package, request_hash, self.require_licensed,
                           now_ms if now_ms is not None else int(time.time() * 1000),
                           self.MAX_AGE_MS)
        return payload


def check_play_verdict(p: dict, package: str, request_hash: str, require_licensed: bool,
                       now_ms: int, max_age_ms: int) -> None:
    req = p.get("requestDetails") or {}
    # The request must be checked first: every other verdict is only meaningful
    # for the request we issued.
    if req.get("requestPackageName") != package:
        raise AttestationError("integrity token for another package")
    if not hmac.compare_digest(str(req.get("requestHash", "")), request_hash):
        raise AttestationError("integrity token not bound to this challenge")
    try:
        ts = int(req.get("timestampMillis", 0))
    except (TypeError, ValueError):
        ts = 0
    if not (now_ms - max_age_ms <= ts <= now_ms + 60_000):
        raise AttestationError("integrity token too old")

    app = p.get("appIntegrity") or {}
    if app.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
        raise AttestationError("app binary not recognized by Play (modified or sideloaded)")
    if app.get("packageName") != package:
        raise AttestationError("integrity verdict for another package")

    labels = (p.get("deviceIntegrity") or {}).get("deviceRecognitionVerdict") or []
    if "MEETS_DEVICE_INTEGRITY" not in labels:
        raise AttestationError("device fails integrity (rooted, emulator or hooked)")

    if require_licensed:
        lic = (p.get("accountDetails") or {}).get("appLicensingVerdict")
        if lic != "LICENSED":
            raise AttestationError("app not installed from Play")


def _google_decoder(package: str, sa_json: str):
    session = None

    def decode(token: str) -> dict:
        nonlocal session
        if not sa_json:
            raise AttestationError("PLAY_SERVICE_ACCOUNT_JSON not configured")
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                sa_json, scopes=["https://www.googleapis.com/auth/playintegrity"])
            session = AuthorizedSession(creds)
        r = session.post(
            f"https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken",
            json={"integrityToken": token}, timeout=15)
        if r.status_code != 200:
            raise AttestationError(f"Play decode failed: HTTP {r.status_code}")
        return r.json().get("tokenPayloadExternal") or {}

    return decode
