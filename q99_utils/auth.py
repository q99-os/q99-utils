"""Local verification of UM access tokens.

``authorize`` mirrors UM ``/v1/validate/`` (order, status codes and bodies as UM
sends them, message under ``error``), so a denial reads the same either way.
"""

import base64
import os
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError

TOKEN_ISSUER = "quantos-um"
LEEWAY_SECONDS = 30

ACCESS_DENIED_MESSAGE = (
    "You do not have permission to access this feature. "
    "Please contact your administrator to request access."
)
MODULE_NOT_LICENSED_MESSAGE = "This is not included in the current contract."
MFA_SETUP_MESSAGE = "Two-factor authentication is required. Please set it up."


class TokenClaims(BaseModel):
    user_id: str
    is_active: bool
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    is_staff: bool = False
    is_superuser: bool = False
    groups: dict[str, list[str]] = {}
    perms: list[str] = []
    blocked: dict[str, list[str]] = {}
    lock: dict | None = None
    mfa_setup_required: bool = False


@lru_cache(maxsize=1)
def public_key() -> RSAPublicKey:
    """``JWT_PUBLIC_KEY``: base64 of the PEM public key."""
    raw = os.environ.get("JWT_PUBLIC_KEY", "").strip()
    if not raw:
        raise RuntimeError("JWT_PUBLIC_KEY is not set")
    try:
        key = load_pem_public_key(base64.b64decode(raw))
    except ValueError as exc:
        raise RuntimeError("JWT_PUBLIC_KEY is not a base64-encoded PEM public key") from exc
    if not isinstance(key, RSAPublicKey):
        raise RuntimeError("JWT_PUBLIC_KEY must be an RSA key")
    return key


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def verify_token(raw: str) -> TokenClaims:
    """Claims of a valid, unexpired access token for an active user, else 401."""
    try:
        payload = jwt.decode(
            raw,
            public_key(),
            algorithms=["RS256"],
            issuer=TOKEN_ISSUER,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iss"]},
        )
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired token.")
    if payload.get("token_type") != "access":
        raise _unauthorized("Not an access token.")
    try:
        claims = TokenClaims.model_validate(payload)
    except ValidationError:
        raise _unauthorized("Malformed token claims.")
    if not claims.is_active:
        raise _unauthorized("User is inactive.")
    return claims


def authorize(
    claims: TokenClaims,
    *,
    staff_required: bool = False,
    permissions_required: list[str] | None = None,
) -> None:
    """Raise the HTTPException UM ``/v1/validate/`` would answer with, if any."""
    if claims.mfa_setup_required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"requires_2fa_setup": True, "error": MFA_SETUP_MESSAGE},
        )

    required = [p.strip() for p in permissions_required or [] if p and p.strip()]

    if (required or staff_required) and claims.lock:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=claims.lock)

    unlicensed = sorted({module for codename in required for module in claims.blocked.get(codename, [])})
    if unlicensed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "module_not_licensed", "error": MODULE_NOT_LICENSED_MESSAGE, "modules": unlicensed},
        )

    if claims.is_superuser:
        return

    if staff_required and not claims.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "staff_required", "error": ACCESS_DENIED_MESSAGE},
        )

    held = set(claims.perms)
    missing = [codename for codename in required if codename not in held]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "missing_permission", "error": ACCESS_DENIED_MESSAGE, "missing_permissions": missing},
        )
