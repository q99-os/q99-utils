"""Webex API client for the organizational files and transcripts index."""

from __future__ import annotations

from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from q99_utils.integrations.core.exceptions import (
    AccessDenied,
    AppCredentialExpired,
    CredentialExpired,
    IntegrationError,
    ResourceNotFound,
)
from q99_utils.models import OnboardingData


WEBEX_API = "https://webexapis.com/v1"
REQUEST_TIMEOUT = 20.0


class WebexClient:
    def __init__(
        self,
        credentials: OnboardingData,
        on_refresh: Callable[[OnboardingData], Awaitable[None]] | None = None,
        reload_credentials: Callable[[], Awaitable[OnboardingData]] | None = None,
        source: str = "webex_archive",
    ) -> None:
        self.credentials = credentials
        self.on_refresh = on_refresh
        self.reload_credentials = reload_credentials
        self.source = source

    async def _refresh(self) -> None:
        creds = self.credentials
        if not (creds.refresh_token and creds.client_id and creds.client_secret):
            raise CredentialExpired("Reconnect Webex to continue.", source=self.source)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{WEBEX_API}/access_token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": creds.client_id,
                        "client_secret": creds.client_secret,
                        "refresh_token": creds.refresh_token,
                    },
                )
        except httpx.HTTPError as exc:
            raise IntegrationError("Webex token refresh is unavailable.") from exc
        if response.status_code >= 400:
            try:
                error = response.json().get("error")
            except (ValueError, AttributeError):
                error = None
            if error == "invalid_client":
                raise AppCredentialExpired(
                    "The Webex application credentials must be updated by an administrator.",
                    source=self.source,
                )
            if error == "invalid_grant" and self.reload_credentials:
                latest = await self.reload_credentials()
                if latest.refresh_token != creds.refresh_token and latest.api_key:
                    self.credentials = latest
                    return
            raise CredentialExpired("Reconnect Webex to continue.", source=self.source)
        try:
            tokens = response.json()
            access_token = tokens["access_token"]
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("Missing access token")
        except (ValueError, KeyError, TypeError) as exc:
            raise IntegrationError("Webex returned an invalid token response.") from exc
        creds.api_key = access_token
        if tokens.get("refresh_token"):
            creds.refresh_token = tokens["refresh_token"]
        if self.on_refresh:
            await self.on_refresh(creds)

    def _check_status(self, status: int, *, download: bool = False) -> None:
        """Map Webex HTTP failures consistently for metadata and content reads."""
        if 200 <= status < 300 and (not download or status == 200):
            return
        match status:
            case 401:
                raise CredentialExpired("Reconnect Webex to continue.", source=self.source)
            case 403:
                raise AccessDenied("The Webex connection cannot access this resource.")
            case 404 | 410:
                raise ResourceNotFound("Webex resource not found.", source=self.source)
            case code if 300 <= code < 400:
                raise IntegrationError("Webex returned an unsupported redirect for this resource.")
            case _:
                operation = "download" if download else "request"
                raise IntegrationError(f"Webex {operation} failed ({status}).")

    @staticmethod
    def _url_kind(url: str) -> str | None:
        """Classify the only provider links that may receive our bearer token."""
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.fragment:
            return None
        host, path = parsed.netloc, parsed.path
        if host in {"webexapis.com", "integration.webexapis.com"} and path.startswith("/v1/contents/"):
            return "content"
        if host == "webexapis.com" and path in {"/v1/events", "/v1/memberships"}:
            return "page"
        if host == "webexapis.com" and path.startswith("/v1/meetingTranscripts/") and path.endswith("/download"):
            return "transcript"
        return None

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        absolute_url: str | None = None,
        method: str = "GET",
    ) -> httpx.Response:
        url = absolute_url or f"{WEBEX_API}{path}"
        if absolute_url and self._url_kind(url) != {"HEAD": "content", "GET": "page"}.get(method):
            raise ValueError("Only supported Webex API links are accepted.")
        for attempt in range(2):
            if not self.credentials.api_key:
                await self._refresh()
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
                    response = await client.request(
                        method, url,
                        params=params,
                        json=json_body,
                        headers={"Authorization": f"Bearer {self.credentials.api_key}"},
                    )
            except httpx.HTTPError as exc:
                raise IntegrationError("Webex is unavailable. Try again later.") from exc
            if response.status_code == 401 and attempt == 0:
                await self._refresh()
                continue
            self._check_status(response.status_code)
            return response
        raise IntegrationError("Webex authentication failed.")

    async def download(self, url: str, max_bytes: int) -> bytes:
        """Read a provider content link with a hard byte cap and no redirects."""
        if self._url_kind(url) not in {"content", "transcript"}:
            raise ValueError("Only Webex content links are accepted.")
        for attempt in range(2):
            if not self.credentials.api_key:
                await self._refresh()
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
                    async with client.stream(
                        "GET", url,
                        headers={"Authorization": f"Bearer {self.credentials.api_key}"},
                    ) as response:
                        if response.status_code == 401 and attempt == 0:
                            await self._refresh()
                            continue
                        self._check_status(response.status_code, download=True)
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > max_bytes:
                                raise IntegrationError("Webex content exceeds the indexing limit.")
                        return bytes(content)
            except httpx.HTTPError as exc:
                raise IntegrationError("Webex is unavailable. Try again later.") from exc
        raise IntegrationError("Webex authentication failed.")

    async def _json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._request(path, params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationError("Webex returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise IntegrationError("Webex returned an invalid response.")
        return payload

    async def file_details(self, file_url: str) -> dict[str, Any]:
        response = await self._request("", absolute_url=file_url, method="HEAD")
        return {
            "content_type": response.headers.get("Content-Type"),
            "content_length": response.headers.get("Content-Length"),
            "content_disposition": response.headers.get("Content-Disposition"),
        }


__all__ = ["WebexClient"]
