"""Checking the token Google signs on every Pub/Sub push."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from q99_utils.integrations.core import IntegrationError
from q99_utils.integrations.core import google_pubsub
from q99_utils.integrations.core.google_pubsub import verify_push_token

AUDIENCE = "https://q99.ai/um/v1/mailbox/webhook/gmail/"


@pytest.fixture
def signing_key(monkeypatch):
    """Sign with a local key and make the JWKS lookup return its public half."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeSigningKey:
        key = private_key.public_key()

    monkeypatch.setattr(
        google_pubsub.PyJWKClient, "get_signing_key_from_jwt", lambda self, token: FakeSigningKey()
    )
    return private_key


def _token(private_key, **overrides) -> str:
    claims = {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "email": "push@acme.iam.gserviceaccount.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_verify_push_token_accepts_valid(signing_key):
    claims = verify_push_token(_token(signing_key), audience=AUDIENCE)

    assert claims["email"] == "push@acme.iam.gserviceaccount.com"


def test_verify_push_token_rejects_wrong_audience(signing_key):
    with pytest.raises(IntegrationError):
        verify_push_token(_token(signing_key, aud="https://elsewhere/"), audience=AUDIENCE)


def test_verify_push_token_rejects_other_issuer(signing_key):
    with pytest.raises(IntegrationError):
        verify_push_token(_token(signing_key, iss="https://evil.example"), audience=AUDIENCE)


def test_verify_push_token_rejects_garbage():
    with pytest.raises(IntegrationError):
        verify_push_token("not-a-jwt", audience=AUDIENCE)
