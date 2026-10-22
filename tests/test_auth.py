"""Local token verification, and authorize() as a replay of UM /v1/validate/."""

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from q99_utils import auth
from q99_utils.auth import TokenClaims, authorize, verify_token


def _keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, base64.b64encode(public_pem).decode()


PRIVATE, PUBLIC_B64 = _keypair()
OTHER_PRIVATE, _ = _keypair()


@pytest.fixture(autouse=True)
def public_key_env(monkeypatch):
    monkeypatch.setenv("JWT_PUBLIC_KEY", PUBLIC_B64)
    auth.public_key.cache_clear()
    yield
    auth.public_key.cache_clear()


def _token(key=PRIVATE, algorithm="RS256", **overrides):
    now = int(time.time())
    payload = {
        "token_type": "access",
        "exp": now + 600,
        "iat": now,
        "jti": "j",
        "iss": "quantos-um",
        "user_id": "7",
        "is_active": True,
        "email": "ada@example.com",
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm=algorithm)


def _status(raw):
    with pytest.raises(HTTPException) as caught:
        verify_token(raw)
    return caught.value.status_code


class TestVerifyToken:

    def test_a_valid_token_gives_its_claims(self):
        claims = verify_token(_token(groups={"app": ["ops"]}, perms=["chat:use"]))
        assert claims.user_id == "7"
        assert claims.groups == {"app": ["ops"]}
        assert claims.perms == ["chat:use"]

    def test_expired(self):
        assert _status(_token(exp=int(time.time()) - 60)) == 401

    def test_expiry_within_leeway_is_accepted(self):
        assert verify_token(_token(exp=int(time.time()) - 5)).user_id == "7"

    def test_wrong_issuer(self):
        assert _status(_token(iss="someone-else")) == 401

    def test_missing_issuer(self):
        assert _status(_token(iss=None)) == 401

    def test_signed_by_another_key(self):
        assert _status(_token(key=OTHER_PRIVATE)) == 401

    def test_tampered_payload(self):
        header, _, signature = _token().split(".")
        forged = base64.urlsafe_b64encode(b'{"user_id":"1","is_superuser":true}').rstrip(b"=").decode()
        assert _status(f"{header}.{forged}.{signature}") == 401

    def test_old_hs256_token(self):
        assert _status(_token(key="123456", algorithm="HS256")) == 401

    def test_a_refresh_token_is_not_an_access_token(self):
        assert _status(_token(token_type="refresh")) == 401

    def test_inactive_user(self):
        assert _status(_token(is_active=False)) == 401

    def test_missing_active_claim(self):
        assert _status(_token(is_active=None)) == 401

    def test_garbage(self):
        assert _status("not-a-jwt") == 401


class TestPublicKeyConfig:

    def test_missing(self, monkeypatch):
        monkeypatch.delenv("JWT_PUBLIC_KEY")
        with pytest.raises(RuntimeError, match="not set"):
            verify_token(_token())

    def test_malformed(self, monkeypatch):
        monkeypatch.setenv("JWT_PUBLIC_KEY", base64.b64encode(b"nope").decode())
        with pytest.raises(RuntimeError, match="PEM"):
            verify_token(_token())


def _claims(**overrides):
    return TokenClaims(user_id="1", is_active=True, **overrides)


def _denial(claims, **kwargs):
    with pytest.raises(HTTPException) as caught:
        authorize(claims, **kwargs)
    return caught.value.status_code, caught.value.detail


LOCK = {"code": "license_locked", "state": "expired", "error": "locked"}


class TestAuthorize:

    def test_no_gate_passes(self):
        authorize(_claims())

    def test_held_permission_passes(self):
        authorize(_claims(perms=["chat:use"]), permissions_required=["chat:use"])

    def test_missing_permission(self):
        status, detail = _denial(_claims(perms=["chat:use"]), permissions_required=["chat:use", "files:read"])
        assert status == 403
        assert detail["code"] == "missing_permission"
        assert detail["missing_permissions"] == ["files:read"]

    def test_staff_required(self):
        status, detail = _denial(_claims(), staff_required=True)
        assert (status, detail["code"]) == (403, "staff_required")
        authorize(_claims(is_staff=True), staff_required=True)

    def test_superuser_skips_role_gates(self):
        authorize(_claims(is_superuser=True), staff_required=True, permissions_required=["files:read"])

    def test_unlicensed_module_blocks_superusers_too(self):
        claims = _claims(is_superuser=True, blocked={"wells.history:read": ["wells.history"]})
        status, detail = _denial(claims, permissions_required=["wells.history:read"])
        assert status == 402
        assert detail["code"] == "module_not_licensed"
        assert detail["modules"] == ["wells.history"]

    def test_module_check_comes_before_the_role_check(self):
        claims = _claims(blocked={"reports:read": ["reports"]})
        assert _denial(claims, permissions_required=["reports:read"])[0] == 402

    def test_lock_only_gates_declared_checks(self):
        authorize(_claims(lock=LOCK))
        assert _denial(_claims(lock=LOCK, perms=["chat:use"]), permissions_required=["chat:use"]) == (402, LOCK)
        assert _denial(_claims(lock=LOCK, is_staff=True), staff_required=True) == (402, LOCK)

    def test_lock_comes_before_the_module_check(self):
        claims = _claims(lock=LOCK, blocked={"reports:read": ["reports"]})
        assert _denial(claims, permissions_required=["reports:read"]) == (402, LOCK)

    def test_mfa_setup_comes_first_even_without_gates(self):
        status, detail = _denial(_claims(mfa_setup_required=True, is_superuser=True))
        assert status == 403
        assert detail["requires_2fa_setup"] is True

    def test_blank_codenames_are_ignored(self):
        authorize(_claims(lock=LOCK), permissions_required=["", "  "])
