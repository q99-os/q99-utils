"""Personal Webex connection for reading rooms and sending messages as the user."""

from __future__ import annotations

from typing import Any

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import IntegrationError, SourceIntegrationInterface, register
from q99_utils.integrations.sources.webex_client import WebexClient
from q99_utils.models import OnboardingData


class WebexMessagingClient(WebexClient):
    async def rooms(self, limit: int = 50) -> list[dict[str, Any]]:
        payload = await self._json("/rooms", params={"max": max(1, min(limit, 100))})
        return [
            {"id": room["id"], "name": room.get("title") or "Untitled space"}
            for room in payload.get("items", [])
            if room.get("id")
        ]

    async def messages(self, room_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not room_id:
            raise ValueError("A Webex space ID is required.")
        payload = await self._json(
            "/messages", params={"roomId": room_id, "max": max(1, min(limit, 100))}
        )
        return [
            {
                "id": message["id"],
                "from": message.get("personEmail") or "unknown",
                "at": message.get("created") or "",
                "text": message.get("text") or "",
            }
            for message in payload.get("items", [])
            if message.get("id") and message.get("text")
        ]

    async def send(
        self, text: str, *, room_id: str | None = None, email: str | None = None
    ) -> dict[str, Any]:
        body = (text or "").strip()
        room_id = (room_id or "").strip()
        email = (email or "").strip()
        if not body:
            raise ValueError("The Webex message is empty.")
        if bool(room_id) == bool(email):
            raise ValueError("Choose one Webex space or one recipient email.")
        target = {"roomId": room_id} if room_id else {"toPersonEmail": email}
        response = await self._request("/messages", method="POST", json_body={**target, "text": body})
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError as exc:
            raise IntegrationError("Webex returned an invalid message response.") from exc
        return {"id": payload.get("id"), "room_id": payload.get("roomId")}


@register(SourceEnum.webex)
class WebexIntegration(SourceIntegrationInterface):
    async def client(self, data: OnboardingData | None = None) -> WebexMessagingClient:
        credentials = await self.with_company_app(data or await self.get_credentials())
        if data is not None:
            return WebexMessagingClient(credentials, source="webex")
        return WebexMessagingClient(
            credentials,
            on_refresh=self.persist_tokens,
            reload_credentials=self.get_credentials,
            source="webex",
        )


__all__ = ["WebexIntegration", "WebexMessagingClient"]
