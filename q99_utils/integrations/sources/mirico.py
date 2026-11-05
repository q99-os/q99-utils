"""Read-only client for Mirico's Analysis Engine API.

The published staging OpenAPI document specifies HTTP bearer authentication and
an ``/engine-api`` server prefix. An API key is required for every data request.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.core.registry import register
from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.models import OnboardingData


STAGING_API_BASE = "https://api.mirico.dev/engine-api"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _api_base(value: str | None) -> str:
    base = (value or STAGING_API_BASE).strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CredentialValidationError(
            "Mirico API Base must be an HTTPS URL without credentials, query, or fragment.",
            source="mirico",
        )
    return base


@register(SourceEnum.mirico)
class MiricoIntegration(SourceIntegrationInterface):
    async def _get(self, path: str, data: OnboardingData | None = None) -> list[dict]:
        credentials = data if data is not None else await self.get_credentials()
        key = credentials.api_key
        if not key or not key.strip():
            raise CredentialValidationError("Mirico requires an API key.", source="mirico")
        base = _api_base(credentials.api_base)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{base}{path}",
                headers={"Authorization": f"Bearer {key.strip()}", "Accept": "application/json"},
            )
        if response.status_code in (401, 403):
            raise CredentialValidationError(
                "Mirico rejected the API key or denied access to the requested data.",
                source="mirico",
            )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            raise IntegrationError("Mirico returned a non-JSON response.") from None
        if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
            raise IntegrationError("Mirico returned an invalid data list.")
        return body

    async def test_connection(self, data: OnboardingData | None = None) -> None:
        """A small authorized read also works when the user has no sites yet."""
        try:
            await self.list_sites(data=data)
        except CredentialValidationError:
            raise
        except (httpx.HTTPError, IntegrationError):
            raise CredentialValidationError(
                "Mirico connection test failed. Check the API Base and access to sites.",
                source="mirico",
            ) from None

    async def list_sites(self, data: OnboardingData | None = None) -> list[dict]:
        return await self._get("/deployments/sites", data=data)

    async def list_deployments(self, data: OnboardingData | None = None) -> list[dict]:
        return await self._get("/deployments/", data=data)


__all__ = ["MiricoIntegration", "STAGING_API_BASE"]
