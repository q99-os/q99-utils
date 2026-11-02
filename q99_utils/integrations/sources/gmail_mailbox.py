"""Gmail mailbox integration — the dedicated company inbox whose attachments are ingested.

Signed in once as that mailbox through the company Google app, so the stored refresh
token is the mailbox's own. Plain HTTP instead of Google's SDK: these are a handful of
calls, and hosts that only need them shouldn't have to install the ``google`` extra.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import httpx

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import (
    PROCESSED_FOLDER,
    AppCredentialExpired,
    CredentialExpired,
    IntegrationError,
    MailAttachment,
    MailboxIntegration,
    MailMessage,
    ResourceNotFound,
    register,
)
from q99_utils.models import OnboardingData

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
DEFAULT_TIMEOUT = 60


def _file_parts(part: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Every part of a message, however deeply nested, that is a downloadable file."""
    if part.get("filename") and (part.get("body") or {}).get("attachmentId"):
        yield part
    for child in part.get("parts") or []:
        yield from _file_parts(child)


@register(SourceEnum.gmail_mailbox)
class GmailMailboxIntegration(MailboxIntegration):

    _processed_label_id: Optional[str] = None

    async def get_access_token(self, data: OnboardingData) -> str:
        """A fresh access token from the stored refresh token."""
        data = await self.with_company_app(data)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": data.refresh_token,
            "client_id": data.client_id,
            "client_secret": data.client_secret,
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=form)

        if response.status_code < 400:
            return response.json()["access_token"]

        error = response.json().get("error") if response.content else None
        if error == "invalid_client":
            raise AppCredentialExpired(
                "Google rejected the company Google application. Its client secret was "
                "rotated or expired, and an administrator has to update it.",
                source=str(self.source),
            )
        if error == "invalid_grant":
            raise CredentialExpired(
                "Google no longer accepts the mailbox connection. Reconnect the mailbox.",
                source=str(self.source),
            )
        raise IntegrationError(f"Google token refresh failed with {response.status_code}: {response.text[:300]}")

    # Push notifications

    async def watch(self, data: OnboardingData) -> Dict[str, Any]:
        """Start (or renew) push notifications for the inbox. Google ends them after 7 days."""
        payload = {
            "topicName": data.pubsub_topic,
            "labelIds": ["INBOX"],
            "labelFilterBehavior": "include",
        }
        token = await self.get_access_token(data)
        return await self._request("POST", f"{GMAIL_API_URL}/watch", token, json=payload)

    async def stop_watch(self, data: OnboardingData) -> None:
        token = await self.get_access_token(data)
        await self._request("POST", f"{GMAIL_API_URL}/stop", token)

    async def mailbox_address(self, data: OnboardingData) -> str:
        """The address of the account that signed in, which is the mailbox being connected."""
        token = await self.get_access_token(data)
        profile = await self._request("GET", f"{GMAIL_API_URL}/profile", token)
        return profile["emailAddress"].lower()

    # Reading the inbox

    async def list_inbox_messages(self, data: OnboardingData, received_after: datetime) -> List[MailMessage]:
        token = await self.get_access_token(data)
        query = f"in:inbox after:{int(received_after.timestamp())}"

        message_ids, page_token = [], None
        while True:
            params = {"q": query, **({"pageToken": page_token} if page_token else {})}
            page = await self._request("GET", f"{GMAIL_API_URL}/messages", token, params=params)
            message_ids += [m["id"] for m in page.get("messages") or []]
            page_token = page.get("nextPageToken")
            if not page_token:
                break

        messages = []
        for message_id in message_ids:
            full = await self._request("GET", f"{GMAIL_API_URL}/messages/{message_id}", token, params={"format": "full"})
            attachments = []
            for part in _file_parts(full.get("payload") or {}):
                headers = {h["name"].lower(): h["value"] for h in part.get("headers") or []}
                attachments.append(MailAttachment(
                    id=part["body"]["attachmentId"],
                    name=part["filename"],
                    content_type=part.get("mimeType") or "",
                    size=part["body"].get("size") or 0,
                    is_inline=headers.get("content-disposition", "").lower().startswith("inline"),
                ))
            messages.append(MailMessage(
                id=message_id,
                received_at=datetime.fromtimestamp(int(full["internalDate"]) / 1000, tz=timezone.utc),
                attachments=attachments,
            ))
        return messages

    async def download_attachment(self, message_id: str, attachment_id: str, data: OnboardingData) -> bytes:
        token = await self.get_access_token(data)
        attachment = await self._request(
            "GET", f"{GMAIL_API_URL}/messages/{message_id}/attachments/{attachment_id}", token
        )
        # base64url, sometimes without padding.
        encoded = attachment["data"]
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))

    async def mark_processed(self, message_id: str, data: OnboardingData) -> None:
        token = await self.get_access_token(data)

        if self._processed_label_id is None:
            labels = await self._request("GET", f"{GMAIL_API_URL}/labels", token)
            existing = [l for l in labels.get("labels") or [] if l.get("name") == PROCESSED_FOLDER]
            if existing:
                self._processed_label_id = existing[0]["id"]
            else:
                created = await self._request("POST", f"{GMAIL_API_URL}/labels", token, json={"name": PROCESSED_FOLDER})
                self._processed_label_id = created["id"]

        await self._request(
            "POST", f"{GMAIL_API_URL}/messages/{message_id}/modify", token,
            json={"addLabelIds": [self._processed_label_id], "removeLabelIds": ["INBOX"]},
        )

    async def _request(
        self, method: str, url: str, token: str,
        json: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.request(
                method, url, headers={"Authorization": f"Bearer {token}"}, json=json, params=params
            )

        if response.status_code == 404:
            raise ResourceNotFound(f"Gmail has no resource at {url}")
        if response.status_code >= 400:
            raise IntegrationError(f"Gmail {method} {url} failed with {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}


__all__ = ["GmailMailboxIntegration"]
