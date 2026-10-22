"""Read-only Fracttal assets with renewable client-credentials authentication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

import httpx

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.core.registry import register
from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.models import OnboardingData


TOKEN_URL = "https://one.fracttal.com/oauth/token"
ASSETS_URL = "https://app.fracttal.com/api/items/"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
ASSET_FILTERS = frozenset({"code", "id", "item_type", "location_code", "active", "available", "is_tree"})


def _json(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        raise IntegrationError("Fracttal returned a non-JSON response.") from None


def _validate_page(start: int, limit: int, filters: Mapping | None) -> None:
    if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Fracttal start must be nonnegative and limit must be between 1 and 100.")
    if filters and set(filters) - ASSET_FILTERS:
        raise ValueError("Unsupported Fracttal asset filter.")


class FracttalSession:
    """One renewable token shared by all reads in this HTTP session."""

    def __init__(self, client: httpx.AsyncClient, credentials: OnboardingData):
        self._client = client
        self._credentials = credentials
        self._token: str | None = None
        self._expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def _issue_token(self) -> None:
        requested_at = time.monotonic()
        response = await self._client.post(
            TOKEN_URL,
            auth=httpx.BasicAuth(self._credentials.client_id, self._credentials.client_secret),
            data={"grant_type": "client_credentials"},
        )
        if response.status_code in (400, 401, 403):
            raise CredentialValidationError("Fracttal rejected the OAuth client credentials.", source="fracttal")
        response.raise_for_status()
        body = _json(response)
        token = body.get("access_token") if isinstance(body, dict) else None
        expiry = body.get("expires_in") if isinstance(body, dict) else None
        token_type = body.get("token_type") if isinstance(body, dict) else None
        try:
            lifetime = float(expiry)
        except (TypeError, ValueError):
            lifetime = 0.0
        if (
            not isinstance(token, str) or not token.strip()
            or not isinstance(token_type, str) or token_type.lower() != "bearer"
            or isinstance(expiry, bool) or not math.isfinite(lifetime) or lifetime <= 0
        ):
            raise IntegrationError("Fracttal returned an invalid OAuth token response.")
        self._token = token
        self._expires_at = requested_at + lifetime - min(30.0, lifetime * 0.1)

    async def authenticate(self) -> None:
        async with self._token_lock:
            if self._token is None or time.monotonic() >= self._expires_at:
                await self._issue_token()

    async def read_assets_page(
        self, *, start: int = 0, limit: int = 100,
        filters: Mapping[str, str | int | bool] | None = None,
    ) -> list[dict]:
        _validate_page(start, limit, filters)
        await self.authenticate()
        token = self._token
        params = {**(filters or {}), "start": start, "limit": limit}
        response = await self._client.get(
            ASSETS_URL, params=params, headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            async with self._token_lock:
                if self._token == token:
                    await self._issue_token()
            response = await self._client.get(
                ASSETS_URL, params=params, headers={"Authorization": f"Bearer {self._token}"},
            )
        if response.status_code in (401, 403):
            raise CredentialValidationError("Fracttal denied asset read access. Verify the client and permissions.", source="fracttal")
        response.raise_for_status()
        body = _json(response)
        if not isinstance(body, dict) or body.get("success") is not True:
            raise IntegrationError("Fracttal did not confirm a successful asset read.")
        rows = body.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or len(rows) > limit:
            raise IntegrationError("Fracttal returned an invalid asset page.")
        return rows

    async def read_assets(
        self, *, limit: int = 100, max_pages: int = 10000,
        filters: Mapping[str, str | int | bool] | None = None,
    ) -> list[dict]:
        """Read until a short page; failures and limits never return partial data."""
        _validate_page(0, limit, filters)
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("Fracttal max_pages must be positive.")
        result: list[dict] = []
        seen: set[bytes] = set()
        for page in range(max_pages):
            rows = await self.read_assets_page(start=page * limit, limit=limit, filters=filters)
            fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).digest()
            if rows and fingerprint in seen:
                raise IntegrationError("Fracttal repeated an asset page; the full read could not be completed.")
            result.extend(rows)
            if len(rows) < limit:
                return result
            seen.add(fingerprint)
        raise IntegrationError("Fracttal exceeded the page limit; the full read could not be completed.")


@register(SourceEnum.fracttal)
class FracttalIntegration(SourceIntegrationInterface):
    @asynccontextmanager
    async def session(self, data: OnboardingData | None = None) -> AsyncIterator[FracttalSession]:
        credentials = data if data is not None else await self.get_credentials()
        if not credentials.client_id or not credentials.client_secret:
            raise CredentialValidationError("Fracttal requires Client ID / Key and Client Secret.", source="fracttal")
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            session = FracttalSession(client, credentials)
            await session.authenticate()
            yield session

    async def test_connection(self, data: OnboardingData | None = None) -> None:
        try:
            async with self.session(data) as session:
                await session.read_assets_page(limit=1)
        except CredentialValidationError:
            raise
        except (httpx.HTTPError, IntegrationError):
            raise CredentialValidationError("Fracttal connection test failed. Verify the client and asset read permissions.", source="fracttal") from None

    async def read_assets_page(
        self, *, start: int = 0, limit: int = 100,
        filters: Mapping[str, str | int | bool] | None = None,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        _validate_page(start, limit, filters)
        async with self.session(data) as session:
            return await session.read_assets_page(start=start, limit=limit, filters=filters)

    async def read_assets(
        self, *, limit: int = 100, max_pages: int = 10000,
        filters: Mapping[str, str | int | bool] | None = None,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        _validate_page(0, limit, filters)
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("Fracttal max_pages must be positive.")
        async with self.session(data) as session:
            return await session.read_assets(limit=limit, max_pages=max_pages, filters=filters)
