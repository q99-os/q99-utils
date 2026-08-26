"""Shared Microsoft Graph authentication.

Every Microsoft-backed integration authenticates the same way: a client-credentials
grant against the tenant's token endpoint, scoped to Graph. Keeping it here means
the flow is written once instead of once per integration.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

import httpx

from q99_utils.integrations.core.exceptions import (
    AppCredentialExpired,
    CredentialExpired,
    IntegrationError,
    ResourceNotFound,
)
from q99_utils.models import OnboardingData

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

APP_REJECTED_MESSAGE = (
    "Microsoft rejected the company Microsoft application. Its client secret was "
    "rotated or expired, and an administrator has to update it."
)
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

DELEGATED_MAIL_SCOPES = "openid profile email offline_access User.Read Mail.Send"

DELEGATED_TEAMS_SCOPES = (
    "openid profile email offline_access User.Read "
    "Team.ReadBasic.All Channel.ReadBasic.All ChannelMessage.Send ChannelMessage.Read.All "
    "Chat.Create ChatMessage.Send Chat.Read User.ReadBasic.All"
)

DEFAULT_TIMEOUT = 120


async def request_graph_token(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """The whole client-credentials token response.

    Callers that cache need ``expires_in``; guessing a lifetime risks serving an
    expired token. Raises ``httpx.HTTPError`` when the tenant rejects the
    credentials, and each host maps that to its own error type.
    """
    token_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": GRAPH_SCOPE,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id), data=token_data
        )
        if response.status_code >= 400 and _is_invalid_client(response):
            raise AppCredentialExpired(APP_REJECTED_MESSAGE)
        response.raise_for_status()
        return response.json()


async def acquire_graph_token(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """Just the access token, for callers that do not cache."""
    payload = await request_graph_token(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        timeout=timeout,
    )
    return payload.get("access_token")


async def refresh_delegated_token(
    *,
    tenant_id: Optional[str],
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: str = DELEGATED_MAIL_SCOPES,
    timeout: int = DEFAULT_TIMEOUT,
    source: Optional[str] = None,
) -> dict:
    """Trade a refresh token for a fresh delegated access token.

    A different grant from :func:`acquire_graph_token`: this one acts on behalf
    of a signed-in user, which is what ``/me`` endpoints require. Returns the
    whole payload, since Microsoft may rotate the refresh token too.

    Falls back to the ``common`` tenant when none is stored.
    """
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": scopes,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id or "common"), data=data
        )
        if response.status_code >= 400 and _is_invalid_client(response):
            raise AppCredentialExpired(APP_REJECTED_MESSAGE, source=source)
        if response.status_code >= 400 and _is_invalid_grant(response):
            raise CredentialExpired(
                "Microsoft no longer accepts this connection. Reconnect the integration "
                "to grant access again.",
                source=source,
            )
        response.raise_for_status()
        return response.json()


def _error_code(response: httpx.Response) -> str:
    """The OAuth error code, or empty when the body is not the JSON they document."""
    try:
        return (response.json() or {}).get("error") or ""
    except ValueError:
        return ""


def _is_invalid_grant(response: httpx.Response) -> bool:
    """Whether the grant is gone for good. Anything else stays a transient failure."""
    return _error_code(response) == "invalid_grant"


def _is_invalid_client(response: httpx.Response) -> bool:
    """Whether the app itself was rejected: its secret was rotated or expired."""
    return _error_code(response) == "invalid_client"


# Requests


async def graph_request(
    *,
    access_token: str,
    url: str,
    method: str = "GET",
    json: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """One Graph call, with the failures callers actually branch on.

    Raises :class:`ResourceNotFound` on 404 and :class:`IntegrationError` on
    anything else, so hosts never have to parse status codes out of a message.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if json is not None:
        headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers=headers, json=json)

    if response.status_code == 404:
        raise ResourceNotFound(f"Microsoft Graph has no resource at {url}")
    if response.status_code >= 400:
        raise IntegrationError(
            f"Microsoft Graph {method} failed with {response.status_code}: {response.text[:300]}"
        )
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


async def graph_paginate(
    *,
    access_token: str,
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield every item across Graph's ``@odata.nextLink`` pages."""
    next_url: Optional[str] = url
    while next_url:
        page = await graph_request(access_token=access_token, url=next_url, timeout=timeout)
        for item in page.get("value") or []:
            yield item
        next_url = page.get("@odata.nextLink")


# Delegated client


class DelegatedTokenExpired(RuntimeError):
    """Graph answered 401; the caller should refresh and retry once."""


class DelegatedGraphClient:
    """Calls Graph as the signed-in user, refreshing the token once on a 401.

    ``refresh_scopes`` has to be what the consent actually granted. Azure AD rejects
    a refresh that asks for a scope the person never agreed to, and it rejects it as
    ``invalid_grant`` — the same answer a revoked account gives, which hosts respond
    to by turning the integration off. So each subclass declares its own set rather
    than inheriting whichever one happened to be the default.

    ``on_refresh`` runs after each refresh: persisting is the host's job, and it
    cannot know a rotated token arrived unless it is told.
    """

    refresh_scopes: str = ""
    timeout_seconds: int = DEFAULT_TIMEOUT

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Refuse a subclass that did not say what to ask the refresh grant for.

        Checked while the module loads, not the first time a token expires: an
        integration that silently turns itself off is much harder to trace back.
        """
        super().__init_subclass__(**kwargs)
        if not cls.refresh_scopes:
            raise TypeError(f"{cls.__name__} must declare refresh_scopes")

    def __init__(
        self,
        credentials: OnboardingData,
        timeout: Optional[int] = None,
        on_refresh: Optional[Callable[[OnboardingData], Awaitable[None]]] = None,
    ) -> None:
        if not credentials or not credentials.api_key:
            raise ValueError("Microsoft credentials are missing an access token")
        self.credentials = credentials
        self._token = credentials.api_key
        self._timeout = self.timeout_seconds if timeout is None else timeout
        self._on_refresh = on_refresh

    @property
    def access_token(self) -> str:
        return self._token

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        try:
            return await self._get_once(endpoint, params, headers)
        except DelegatedTokenExpired:
            await self.refresh()
            return await self._get_once(endpoint, params, headers)

    async def post(
        self,
        endpoint: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            return await self._post_once(endpoint, body, params)
        except DelegatedTokenExpired:
            await self.refresh()
            return await self._post_once(endpoint, body, params)

    async def _get_once(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        request_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        request_headers.update(headers or {})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{GRAPH_BASE_URL}{endpoint}", headers=request_headers, params=params or {}
            )
        return self._read(response, "GET", endpoint)

    async def _post_once(
        self,
        endpoint: str,
        body: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{GRAPH_BASE_URL}{endpoint}",
                headers=headers,
                json=body or {},
                params=params or {},
            )
        return self._read(response, "POST", endpoint)

    def _read(self, response: httpx.Response, method: str, endpoint: str) -> Dict[str, Any]:
        """The one place that decides what a status code means for this client."""
        if response.status_code == 401:
            raise DelegatedTokenExpired()
        if response.status_code == 404:
            raise ResourceNotFound(f"Microsoft Graph {method} found no resource at {endpoint}")
        if response.status_code == 202 or not response.content:
            return {}
        response.raise_for_status()
        return response.json()

    async def refresh(self) -> None:
        creds = self.credentials
        payload = await refresh_delegated_token(
            tenant_id=creds.tenant_id,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            refresh_token=creds.refresh_token,
            scopes=self.refresh_scopes,
            source=creds.source,
        )
        self._token = payload["access_token"]
        creds.api_key = payload["access_token"]
        if payload.get("refresh_token"):
            creds.refresh_token = payload["refresh_token"]

        if self._on_refresh:
            await self._on_refresh(creds)


class MicrosoftGraphAuth:
    """Resolves credentials, then delegates to :func:`acquire_graph_token`.

    Mixed into the integrations rather than inherited from, so each one keeps
    ``SourceIntegrationInterface`` as its real base.
    """

    async def get_access_token(self, data: Optional[OnboardingData] = None) -> Optional[str]:
        credentials = data if data is not None else await self.get_credentials()
        credentials = await self.with_company_app(credentials)
        self.credentials = credentials.model_dump()

        return await acquire_graph_token(
            tenant_id=self.credentials["tenant_id"],
            client_id=self.credentials["client_id"],
            client_secret=self.credentials["client_secret"],
        )


__all__ = [
    "APP_REJECTED_MESSAGE",
    "DELEGATED_MAIL_SCOPES",
    "DELEGATED_TEAMS_SCOPES",
    "DelegatedGraphClient",
    "DelegatedTokenExpired",
    "GRAPH_BASE_URL",
    "GRAPH_SCOPE",
    "MicrosoftGraphAuth",
    "acquire_graph_token",
    "request_graph_token",
    "graph_paginate",
    "graph_request",
    "refresh_delegated_token",
]
