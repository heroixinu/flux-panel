#!/usr/bin/env python3
"""Exercise WebAuthn cryptography over the real backend HTTP API (JVM/AOT/native).

Only run on a disposable smoke_backend.py fixture. Keys are synthetic and stored
in the temporary runner directory solely to verify restart and backup restoration.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding

from smoke_backend import post, login, sql

ORIGIN = os.environ.get("PASSKEY_ORIGIN", "http://localhost:6365")
RP = "localhost"
ADMIN = ("ci_smoke_admin", "ci-admin-new-password")
USER = ("ci_smoke_user", "ci-smoke-new-password")


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sha(data):
    return hashlib.sha256(data).digest()


def cbor_head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    if n <= 255:
        return bytes([major << 5 | 24, n])
    if n <= 65535:
        return bytes([major << 5 | 25]) + struct.pack(">H", n)
    return bytes([major << 5 | 26]) + struct.pack(">I", n)


def cbor(value):
    # Minimal deterministic CBOR encoding for this virtual test authenticator.
    if isinstance(value, int):
        return cbor_head(0 if value >= 0 else 1, value if value >= 0 else -1 - value)
    if isinstance(value, str):
        data = value.encode()
        return cbor_head(3, len(data)) + data
    if isinstance(value, bytes):
        return cbor_head(2, len(value)) + value
    if isinstance(value, dict):
        return cbor_head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(type(value))


class Authenticator:
    def __init__(self, algorithm="ec", backup=False, saved=None):
        if saved:
            self.key = serialization.load_pem_private_key(saved["pem"].encode(), password=None)
            self.id = unb64(saved["id"])
            self.handle = saved["handle"]
            self.backup = saved["backup"]
        else:
            self.key = ec.generate_private_key(ec.SECP256R1()) if algorithm == "ec" else rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self.id = os.urandom(32)
            self.handle = None
            self.backup = backup

    def save(self):
        return {"pem": self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()).decode(),
                "id": b64(self.id), "handle": self.handle, "backup": self.backup}

    def cose(self):
        k = self.key.public_key().public_numbers()
        if isinstance(k, ec.EllipticCurvePublicNumbers):
            return cbor({1: 2, 3: -7, -1: 1, -2: k.x.to_bytes(32, "big"), -3: k.y.to_bytes(32, "big")})
        return cbor({1: 3, 3: -257, -1: k.n.to_bytes(256, "big"), -2: k.e.to_bytes(3, "big")})

    def client(self, ceremony, typ, origin=ORIGIN, **extra):
        return json.dumps(dict(type=typ, challenge=ceremony["options"]["challenge"], origin=origin,
                               crossOrigin=False) | extra, separators=(",", ":")).encode()

    def envelope(self, ceremony, response, **extra):
        return {"requestId": ceremony["requestId"], "credential": {"id": b64(self.id), "rawId": b64(self.id),
                "type": "public-key", "response": response, "clientExtensionResults": {}}, **extra}

    def registration(self, ceremony, **extra):
        opts = ceremony["options"]
        assert opts["rp"]["id"] == RP
        assert opts["authenticatorSelection"]["residentKey"] == "required"
        assert opts["authenticatorSelection"]["userVerification"] == "required"
        self.handle = opts["user"]["id"]
        flags = 0x45 | (0x18 if self.backup else 0)
        auth = sha(RP.encode()) + bytes([flags]) + b"\0" * 4 + b"\0" * 16 + struct.pack(">H", len(self.id)) + self.id + self.cose()
        att = cbor({"fmt": "none", "authData": auth, "attStmt": {}})
        return self.envelope(ceremony, {"clientDataJSON": b64(self.client(ceremony, "webauthn.create")),
                                       "attestationObject": b64(att), "transports": ["internal"]},
                             label="CI virtual authenticator", **extra)

    def assertion(self, ceremony, counter, *, origin=ORIGIN, uv=True, corrupt=False, **extra):
        opts = ceremony["options"]
        assert opts["rpId"] == RP and opts["userVerification"] == "required"
        assert not opts.get("allowCredentials"), "Expected a discoverable credential ceremony"
        client = self.client(ceremony, "webauthn.get", origin=origin, **extra)
        flags = 0x01 | (0x04 if uv else 0) | (0x18 if self.backup else 0)
        auth = sha(RP.encode()) + bytes([flags]) + struct.pack(">I", counter)
        message = auth + sha(client)
        if isinstance(self.key, ec.EllipticCurvePrivateKey):
            signature = self.key.sign(message, ec.ECDSA(hashes.SHA256()))
        else:
            signature = self.key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        if corrupt:
            signature = bytes([signature[0] ^ 1]) + signature[1:]
        return self.envelope(ceremony, {"clientDataJSON": b64(client), "authenticatorData": b64(auth),
                             "signature": b64(signature), "userHandle": self.handle})


def call(path, data=None, token=None, expected=0):
    return post("passkey/" + path, data, token, expected=expected)


def opts(purpose="login", token=None):
    return call(purpose + "/options", token=token)


def assert_key(key, counter, purpose="login", token=None, expected=0, **extra):
    return call(purpose + "/finish", key.assertion(opts(purpose, token), counter, **extra), token, expected)


def proof(key, counter, token):
    return assert_key(key, counter, "reauth", token)["proof"]


def enroll(key, token, password=None, reauth_proof=None):
    authorization = {"password": password} if password is not None else {"proof": reauth_proof}
    ceremony = call("register/options", authorization, token)
    payload = key.registration(ceremony)
    call("register/finish", payload, token)
    call("register/finish", payload, token, expected=None)  # replay


def initial(state):
    modes = call("modes")
    assert modes["passwordEnabled"] and modes["passkeyEnabled"] and modes["origin"] == ORIGIN
    admin, ordinary = login(*ADMIN)["token"], login(*USER)["token"]
    call("list", expected=401)
    call("register/options", {"password": "wrong"}, admin, expected=None)
    call("policy", {"passwordEnabled": False}, ordinary, expected=None)

    a, u = Authenticator(), Authenticator("rsa", backup=True)
    first = call("register/options", {"password": ADMIN[1]}, admin)
    payload = a.registration(first)
    call("register/finish", payload, ordinary, expected=None)  # wrong session
    call("register/finish", payload, admin)
    call("register/finish", payload, admin, expected=None)
    assert not call("list", token=admin)["allUsersReady"]
    assert_key(a, 1, origin="https://wrong.example", expected=None)
    assert_key(a, 1, uv=False, expected=None)
    assert_key(a, 1, corrupt=True, expected=None)
    assert_key(a, 1, crossOrigin=True, expected=None)
    wrong = a.assertion(opts(), 1)
    wrong["requestId"] = opts()["requestId"]
    call("login/finish", wrong, expected=None)  # challenge substitution
    c = opts()
    assertion = a.assertion(c, 1)
    result = call("login/finish", assertion)
    assert result["name"] == ADMIN[0] and result["role_id"] == 0
    call("login/finish", assertion, expected=None)
    assert_key(a, 1, expected=None)  # replay of counter with fresh challenge
    call("policy", {"passwordEnabled": False, "proof": proof(a, 2, admin)}, admin, expected=None)
    enroll(u, ordinary, password=USER[1])
    assert assert_key(u, 0)["name"] == USER[0]  # synced RSA credential with counter=0
    assert_key(u, 0, "reauth", admin, expected=None)  # cross-account proof
    call("policy", {"passwordEnabled": False, "proof": proof(u, 0, ordinary)}, ordinary, expected=None)
    call("policy", {"passwordEnabled": False, "proof": proof(a, 3, admin)}, admin)
    assert not call("modes")["passwordEnabled"]
    login(*ADMIN, expected=None)
    login(*USER, expected=None)
    assert not call("list", token=admin)["passwordEnabled"]
    assert assert_key(a, 4)["name"] == ADMIN[0]
    key_id = call("list", token=admin)["keys"][0]["id"]
    call("delete", {"id": key_id, "proof": proof(a, 5, admin)}, admin, expected=None)
    call("register/options", {"password": ADMIN[1]}, admin, expected=None)
    another = Authenticator()
    enroll(another, admin, reauth_proof=proof(a, 6, admin))
    assert assert_key(another, 1)["name"] == ADMIN[0]
    second = next(k for k in call("list", token=admin)["keys"] if k["id"] != key_id)
    call("delete", {"id": second["id"], "proof": proof(a, 7, admin)}, admin)
    assert len(call("list", token=admin)["keys"]) == 1
    assert_key(another, 2, expected=None)

    assert sql("SELECT password_enabled FROM passkey_policy WHERE id=1") == "0"
    state.write_text(json.dumps({"admin": a.save(), "user": u.save()}))
    state.chmod(0o600)
    print("WebAuthn ES256/RS256 registration, discoverable login, signature, origin, UV, replay, authorization and password policy passed")


def restart(state):
    saved = json.loads(state.read_text())
    a, u = Authenticator(saved=saved["admin"]), Authenticator(saved=saved["user"])
    assert not call("modes")["passwordEnabled"]
    login(*ADMIN, expected=None)
    admin = assert_key(a, 8)["token"]
    assert assert_key(u, 0)["name"] == USER[0]
    assert len(call("list", token=admin)["keys"]) == 1
    call("policy", {"passwordEnabled": True, "proof": proof(a, 9, admin)}, admin)
    assert call("modes")["passwordEnabled"]
    assert login(*ADMIN)["role_id"] == 0
    print("Passkey credentials and password-only policy persisted across restart/restore")


def recovery():
    m = call("modes")
    assert m["recovery"] and m["passwordEnabled"] and not m["storedPasswordEnabled"]
    admin = login(*ADMIN)["token"]
    call("policy", {"passwordEnabled": True, "password": "wrong"}, admin, expected=None)
    call("policy", {"passwordEnabled": True, "password": ADMIN[1]}, admin)
    assert call("modes")["storedPasswordEnabled"]
    print("Emergency password recovery restored the persistent policy")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--recovery", action="store_true")
    args = parser.parse_args()
    if args.recovery:
        recovery()
    elif args.restart:
        restart(args.state)
    else:
        initial(args.state)
