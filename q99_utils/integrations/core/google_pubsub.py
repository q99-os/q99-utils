"""Verifying the OIDC token Google attaches to every Pub/Sub push.

A push endpoint is public, so this token is what proves a request came from the
client's push subscription and not from anyone who found the URL.
"""

from __future__ import annotations

from typing import Any, Dict

import jwt
from jwt import PyJWKClient

from q99_utils.integrations.core.exceptions import IntegrationError

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

_jwks_client = PyJWKClient(GOOGLE_CERTS_URL)


def verify_push_token(token: str, *, audience: str) -> Dict[str, Any]:
    """The token's claims, or ``IntegrationError`` when it isn't Google's or isn't for us."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, signing_key.key, algorithms=["RS256"], audience=audience)
    except jwt.PyJWTError as exc:
        raise IntegrationError(f"Invalid Pub/Sub push token: {exc}") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise IntegrationError(f"Pub/Sub push token has an unexpected issuer: {claims.get('iss')}")
    return claims


__all__ = ["verify_push_token"]
