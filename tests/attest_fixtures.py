"""Synthetic App Attest PKI: a fake "Apple" root, an intermediate, and a
credential certificate carrying the nonce extension, built exactly the way
Apple's are, so the real verifier runs end to end in tests."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import cbor2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from techflip.api.attest import AAGUID_PROD, NONCE_OID

APP_ID = "ABCDE12345.fr.techflip.app"


def _sha(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, pub, signer, ca: bool, extra=None):
    now = datetime.now(timezone.utc)
    b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    for ext in extra or ():
        b = b.add_extension(ext, critical=False)
    return b.sign(signer, hashes.SHA256())


def _nonce_ext(nonce: bytes) -> x509.UnrecognizedExtension:
    octet = b"\x04" + bytes([len(nonce)]) + nonce
    tagged = b"\xa1" + bytes([len(octet)]) + octet
    seq = b"\x30" + bytes([len(tagged)]) + tagged
    return x509.UnrecognizedExtension(NONCE_OID, seq)


class FakeApple:
    def __init__(self):
        self.root_key = ec.generate_private_key(ec.SECP384R1())
        self.root = _cert(_name("Test App Attestation Root CA"), _name("Test App Attestation Root CA"),
                          self.root_key.public_key(), self.root_key, ca=True)
        self.inter_key = ec.generate_private_key(ec.SECP384R1())
        self.inter = _cert(_name("Test App Attestation CA 1"), self.root.subject,
                           self.inter_key.public_key(), self.root_key, ca=True)

    @property
    def root_pem(self) -> bytes:
        return self.root.public_bytes(serialization.Encoding.PEM)


class FakeDevice:
    """One app install: a Secure Enclave key and a signature counter."""

    def __init__(self, apple: FakeApple, app_id: str = APP_ID, aaguid: bytes = AAGUID_PROD):
        self.apple = apple
        self.app_id = app_id
        self.aaguid = aaguid
        self.key = ec.generate_private_key(ec.SECP256R1())
        point = self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                   serialization.PublicFormat.UncompressedPoint)
        self.key_id_raw = _sha(point)
        self.key_id = base64.b64encode(self.key_id_raw).decode()
        self.counter = 0

    def attest(self, challenge: str, nonce_override: bytes | None = None) -> str:
        auth = (_sha(self.app_id.encode()) + b"\x40" + (0).to_bytes(4, "big") + self.aaguid
                + len(self.key_id_raw).to_bytes(2, "big") + self.key_id_raw)
        nonce = nonce_override or _sha(auth + _sha(challenge.encode()))
        cred = _cert(_name(self.key_id_raw.hex()), self.apple.inter.subject,
                     self.key.public_key(), self.apple.inter_key, ca=False,
                     extra=[_nonce_ext(nonce)])
        obj = {"fmt": "apple-appattest",
               "attStmt": {"x5c": [cred.public_bytes(serialization.Encoding.DER),
                                   self.apple.inter.public_bytes(serialization.Encoding.DER)],
                           "receipt": b"receipt"},
               "authData": auth}
        return base64.b64encode(cbor2.dumps(obj)).decode()

    def assert_(self, client_data: str, counter: int | None = None) -> str:
        self.counter = self.counter + 1 if counter is None else counter
        auth = _sha(self.app_id.encode()) + b"\x00" + self.counter.to_bytes(4, "big")
        nonce = _sha(auth + _sha(client_data.encode()))
        sig = self.key.sign(nonce, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(cbor2.dumps({"signature": sig, "authenticatorData": auth})).decode()
