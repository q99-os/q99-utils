"""Google SSO OAuth client integration — credential validation only.

These credentials back Google SSO login, which the User Manager performs; there
is nothing for this class to read from Google. All it does is prove, at
onboarding time, that a client ID and secret are real.

Google publishes no endpoint for verifying an OAuth *web* client — there is no
client-credentials flow, and the authorization-code flow needs a user redirect.
What works instead is sending a deliberately invalid authorization code: Google
authenticates the client *before* it validates the grant, so the error separates
the two failures.

    invalid_client  ->  the client ID or secret is wrong
    invalid_grant   ->  the client is fine; only the throwaway code was rejected

Nothing is issued or consumed either way. Anything else — including an
unexpected success — is treated as a failure: a probe that wrongly reports bad
credentials as good is worse than no probe.

Note this cannot check that the redirect URI is registered, which is the other
common misconfiguration. A credential passing here does not guarantee login works.
"""

from __future__ import annotations

from typing import Optional

import httpx

from q99_utils.integrations.core import (
    CredentialValidationError,
    SourceIntegrationInterface,
    register,
)
from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

TIMEOUT = 30

# Deliberately not a real code. No redirect_uri is sent: Google checks the client
# before the grant, so the probe resolves without one.
PROBE_CODE = "quantos-credential-probe"

CLIENT_ACCEPTED_ERROR = "invalid_grant"
CLIENT_REJECTED_ERROR = "invalid_client"

_REJECTED_MESSAGE = (
    "Google rejected these credentials. Verify the client ID and client secret "
    "match the OAuth client in your Google Cloud project."
)


@register(SourceEnum.google_sso)
class GoogleSsoIntegration(SourceIntegrationInterface):

    async def test_connection(self, data: Optional[OnboardingData] = None) -> None:
        """Raise ``CredentialValidationError`` unless the credentials check out."""
        credentials = data if data is not None else await self.get_credentials()

        if not credentials.client_id or not credentials.client_secret:
            raise CredentialValidationError(
                "Google SSO needs both a client ID and a client secret.",
                source=str(self.source),
            )

        payload = {
            "grant_type": "authorization_code",
            "code": PROBE_CODE,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                # No raise_for_status: the 400/401 body is precisely what we need.
                response = await client.post(GOOGLE_TOKEN_URL, data=payload)
        except httpx.HTTPError:
            logger.warning("Google token endpoint unreachable", exc_info=True)
            raise CredentialValidationError(
                "Could not reach Google to verify the credentials. Check that this "
                "deployment has outbound access to oauth2.googleapis.com.",
                source=str(self.source),
            )

        try:
            body = response.json()
        except ValueError:
            logger.warning(
                "Google token endpoint returned a non-JSON body (HTTP %s)",
                response.status_code,
            )
            raise CredentialValidationError(_REJECTED_MESSAGE, source=str(self.source))

        error = body.get("error") if isinstance(body, dict) else None

        if error == CLIENT_ACCEPTED_ERROR:
            return

        if error != CLIENT_REJECTED_ERROR:
            # Unrecognised shape — fail closed rather than guess.
            logger.warning(
                "Unexpected Google token response (HTTP %s, error=%r)",
                response.status_code,
                error,
            )

        raise CredentialValidationError(_REJECTED_MESSAGE, source=str(self.source))


__all__ = [
    "GoogleSsoIntegration",
    "GOOGLE_TOKEN_URL",
    "PROBE_CODE",
    "CLIENT_ACCEPTED_ERROR",
    "CLIENT_REJECTED_ERROR",
]
