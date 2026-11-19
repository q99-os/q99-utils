"""Delegated, read-only access to Webex Messaging and Meetings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import SourceIntegrationInterface, register
from q99_utils.integrations.core.exceptions import (
    AccessDenied,
    AppCredentialExpired,
    CredentialExpired,
    CredentialValidationError,
    IntegrationError,
    ResourceNotFound,
)
from q99_utils.models import OnboardingData


WEBEX_API = "https://webexapis.com/v1"
REQUEST_TIMEOUT = 20.0
MAX_SPACES = 20
MAX_MESSAGES_PER_SPACE = 100
MAX_TRANSCRIPT_BYTES = 1_000_000


class WebexClient:
    def __init__(
        self,
        credentials: OnboardingData,
        on_refresh: Callable[[OnboardingData], Awaitable[None]] | None = None,
    ) -> None:
        self.credentials = credentials
        self.on_refresh = on_refresh

    async def _refresh(self) -> None:
        creds = self.credentials
        if not (creds.refresh_token and creds.client_id and creds.client_secret):
            raise CredentialExpired("Reconnect Webex to continue.", source="webex")
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
        if response.status_code in (401, 403) or "invalid_client" in response.text:
            raise AppCredentialExpired("The Webex application must be updated by an administrator.", source="webex")
        if response.status_code >= 400:
            raise CredentialExpired("Reconnect Webex to continue.", source="webex")
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

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        absolute_url: str | None = None,
        method: str = "GET",
    ) -> httpx.Response:
        url = absolute_url or f"{WEBEX_API}{path}"
        if absolute_url:
            parsed = urlsplit(url)
            transcript = parsed.path.startswith("/v1/meetingTranscripts/") and parsed.path.endswith("/download")
            attachment = parsed.path.startswith("/v1/contents/") and method == "HEAD"
            if parsed.scheme != "https" or parsed.netloc != "webexapis.com" or not (transcript or attachment):
                raise ValueError("Only Webex API download links are accepted.")
        for attempt in range(2):
            if not self.credentials.api_key:
                await self._refresh()
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
                    response = await client.request(
                        method, url,
                        params=params,
                        headers={"Authorization": f"Bearer {self.credentials.api_key}"},
                    )
            except httpx.HTTPError as exc:
                raise IntegrationError("Webex is unavailable. Try again later.") from exc
            if response.status_code == 401 and attempt == 0:
                await self._refresh()
                continue
            if response.status_code == 401:
                raise CredentialExpired("Reconnect Webex to continue.", source="webex")
            if response.status_code == 403:
                raise AccessDenied("Your Webex account cannot access this resource.")
            if response.status_code == 404:
                raise ResourceNotFound("Webex resource not found.", source="webex")
            if 300 <= response.status_code < 400:
                raise IntegrationError("Webex returned an unsupported redirect for this resource.")
            if response.status_code >= 400:
                raise IntegrationError(f"Webex request failed ({response.status_code}).")
            return response
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

    async def spaces(self, limit: int = 100) -> list[dict[str, Any]]:
        payload = await self._json("/rooms", params={"max": min(max(limit, 1), 100)})
        return payload.get("items") or []

    async def search_spaces(self, query: str) -> dict[str, Any]:
        rooms = await self.spaces(100)
        wanted = query.strip().casefold()
        if not wanted:
            raise ValueError("Search text is required.")
        return {
            "spaces": [room for room in rooms if wanted in (room.get("title") or "").casefold()],
            "partial": len(rooms) == 100,
            "note": "Search covers the first page of spaces the account can access.",
        }

    async def messages(self, room_id: str, limit: int = 50) -> list[dict[str, Any]]:
        payload = await self._json(
            "/messages",
            params={"roomId": room_id, "max": min(max(limit, 1), MAX_MESSAGES_PER_SPACE)},
        )
        return payload.get("items") or []

    async def search_messages(
        self, query: str, room_id: str | None = None, limit: int = 20,
    ) -> dict[str, Any]:
        """Bounded live search. Report coverage rather than implying full history was searched."""
        wanted = query.strip().casefold()
        if not wanted:
            raise ValueError("Search text is required.")
        rooms = [{"id": room_id}] if room_id else await self.spaces(100)
        hits: list[dict[str, Any]] = []
        searched = 0
        cap = min(max(limit, 1), 50)
        for room in rooms[:MAX_SPACES]:
            rid = room.get("id")
            if not rid:
                continue
            searched += 1
            for message in await self.messages(rid, MAX_MESSAGES_PER_SPACE):
                content = message.get("text") or message.get("markdown") or ""
                if wanted in content.casefold():
                    hits.append(message)
                    if len(hits) >= cap:
                        break
            if len(hits) >= cap:
                break
        return {
            "messages": hits,
            "spaces_searched": searched,
            "spaces_available_on_first_page": len(rooms),
            "partial": len(rooms) > searched or len(hits) >= cap,
            "note": "Search covers recent messages in the reported spaces, not all Webex history.",
        }

    async def files(self, room_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {"message_id": item.get("id"), "room_id": room_id, "created": item.get("created"), "urls": item["files"]}
            for item in await self.messages(room_id, limit)
            if item.get("files")
        ]

    async def search_files(self, query: str, room_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Find recent attachments by the message around them, not file contents."""
        wanted = query.strip().casefold()
        if not wanted:
            raise ValueError("Search text is required.")
        rooms = [{"id": room_id}] if room_id else await self.spaces(100)
        hits: list[dict[str, Any]] = []
        searched = 0
        cap = min(max(limit, 1), 50)
        for room in rooms[:MAX_SPACES]:
            rid = room.get("id")
            if not rid:
                continue
            searched += 1
            for message in await self.messages(rid, MAX_MESSAGES_PER_SPACE):
                context = message.get("text") or message.get("markdown") or ""
                if message.get("files") and wanted in context.casefold():
                    hits.append({"room_id": rid, "message_id": message.get("id"), "files": message["files"], "context": context})
                    if len(hits) >= cap:
                        break
            if len(hits) >= cap:
                break
        return {
            "files": hits,
            "spaces_searched": searched,
            "partial": len(rooms) > searched or len(hits) >= cap,
            "note": "Matches recent attachment messages, not file names or file contents.",
        }

    async def file_details(self, file_url: str) -> dict[str, Any]:
        response = await self._request("", absolute_url=file_url, method="HEAD")
        return {
            "content_type": response.headers.get("Content-Type"),
            "content_length": response.headers.get("Content-Length"),
            "content_disposition": response.headers.get("Content-Disposition"),
        }

    async def meetings(self, days_back: int = 30, limit: int = 50) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        payload = await self._json("/meetings", params={
            "meetingType": "meeting",
            "from": (now - timedelta(days=min(max(days_back, 1), 90))).isoformat(),
            "to": (now + timedelta(days=1)).isoformat(),
            "max": min(max(limit, 1), 100),
        })
        return payload.get("items") or []

    async def recordings(self, meeting_id: str) -> list[dict[str, Any]]:
        payload = await self._json("/recordings", params={"meetingId": meeting_id})
        return payload.get("items") or []

    async def transcripts(self, meeting_id: str, include_text: bool = False) -> list[dict[str, Any]]:
        payload = await self._json("/meetingTranscripts", params={"meetingId": meeting_id})
        items = payload.get("items") or []
        if not include_text:
            return items
        enriched = []
        for item in items[:3]:
            link = item.get("txtDownloadLink")
            if not link:
                enriched.append(item)
                continue
            response = await self._request("", absolute_url=link)
            if len(response.content) > MAX_TRANSCRIPT_BYTES:
                raise IntegrationError("Transcript is too large for a live answer.")
            enriched.append({**item, "text": response.text})
        return enriched

    async def summary(self, meeting_id: str) -> list[dict[str, Any]]:
        payload = await self._json("/meetingSummaries", params={"meetingId": meeting_id})
        return payload.get("items") or []


@register(SourceEnum.webex)
class WebexIntegration(SourceIntegrationInterface):
    async def client(self, data: OnboardingData | None = None) -> WebexClient:
        if data is not None:
            return WebexClient(await self.with_company_app(data))
        credentials = await self.with_company_app(await self.get_credentials())
        return WebexClient(credentials, on_refresh=self.persist_tokens)

    async def test_connection(self, data: OnboardingData | None = None) -> None:
        try:
            rooms = await (await self.client(data))._json("/rooms", params={"max": 1})
        except (AccessDenied, CredentialExpired) as exc:
            raise CredentialValidationError("Webex did not authorize this account.", source="webex") from exc
        if not isinstance(rooms.get("items"), list):
            raise CredentialValidationError("Webex returned an invalid spaces response.", source="webex")


__all__ = ["WebexClient", "WebexIntegration"]
