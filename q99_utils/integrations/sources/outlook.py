"""Outlook integration — sending mail through Microsoft Graph.

Two callers, two grants. The MCP server sends *as the signed-in user* over
``/me/sendMail`` with a delegated token; the user manager sends transactional
mail *as a service mailbox* over ``/users/{sender}/sendMail`` with an app-only
token. What they share is the message payload and the base URL, so those live
here and each host keeps its own grant.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

import httpx

from q99_utils.integrations.core import (
    GRAPH_BASE_URL,
    SourceIntegrationInterface,
    refresh_delegated_token,
    register,
)
from q99_utils.enums import SourceEnum
from q99_utils.logger import get_logger
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

SEND_MAIL_AS_USER = "/me/sendMail"
SEND_MAIL_AS_MAILBOX = "/users/{sender}/sendMail"

FILE_ATTACHMENT_TYPE = "#microsoft.graph.fileAttachment"

HTML_CONTENT = "HTML"
TEXT_CONTENT = "Text"

DEFAULT_TIMEOUT = 30


# Message payload


def recipient_list(addresses: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    """Addresses in the shape Graph expects for to/cc/bcc."""
    return [{"emailAddress": {"address": a}} for a in (addresses or []) if a]


def file_attachment(*, name: str, content_b64: str, content_type: Optional[str] = None) -> Dict[str, Any]:
    """One base64 attachment entry."""
    attachment = {
        "@odata.type": FILE_ATTACHMENT_TYPE,
        "name": name,
        "contentBytes": content_b64,
    }
    if content_type:
        attachment["contentType"] = content_type
    return attachment


def build_message(
    *,
    subject: str,
    body: str,
    to: Sequence[str],
    cc: Optional[Sequence[str]] = None,
    bcc: Optional[Sequence[str]] = None,
    reply_to: Optional[Sequence[str]] = None,
    content_type: str = HTML_CONTENT,
    attachments: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A Graph ``message`` resource ready to post.

    Optional recipient lists are left out entirely when empty rather than sent
    as ``[]``, which is how Graph distinguishes "none" from "clear these".
    """
    message: Dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body},
        "toRecipients": recipient_list(to),
    }
    if cc:
        message["ccRecipients"] = recipient_list(cc)
    if bcc:
        message["bccRecipients"] = recipient_list(bcc)
    if reply_to:
        message["replyTo"] = recipient_list(reply_to)
    if attachments:
        message["attachments"] = list(attachments)
    return message


# Delegated client


class DelegatedTokenExpired(RuntimeError):
    """Graph answered 401; the caller should refresh and retry once."""


class GraphMailClient:
    """POSTs to Graph on behalf of a user, refreshing the token once on 401.

    ``on_refresh`` runs after each refresh: persisting is the host's job, and it
    cannot know a rotated token arrived unless it is told.
    """

    def __init__(
        self,
        credentials: OnboardingData,
        timeout: int = DEFAULT_TIMEOUT,
        on_refresh: Optional[Callable[[OnboardingData], Awaitable[None]]] = None,
    ) -> None:
        if not credentials or not credentials.api_key:
            raise ValueError("Outlook credentials are missing an access token")
        self.credentials = credentials
        self._token = credentials.api_key
        self._timeout = timeout
        self._on_refresh = on_refresh

    @property
    def access_token(self) -> str:
        return self._token

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

        if response.status_code == 401:
            raise DelegatedTokenExpired()
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
            source=creds.source,
        )
        self._token = payload["access_token"]
        creds.api_key = payload["access_token"]
        if payload.get("refresh_token"):
            creds.refresh_token = payload["refresh_token"]

        if self._on_refresh:
            await self._on_refresh(creds)

    async def send_mail(
        self,
        *,
        subject: str,
        html: str,
        to: Sequence[str],
        cc: Optional[Sequence[str]] = None,
        bcc: Optional[Sequence[str]] = None,
        attachments: Optional[Sequence[Dict[str, Any]]] = None,
        save_to_sent_items: bool = True,
    ) -> Dict[str, Any]:
        message = build_message(
            subject=subject, body=html, to=to, cc=cc, bcc=bcc, attachments=attachments
        )
        return await self.post(
            SEND_MAIL_AS_USER,
            body={"message": message, "saveToSentItems": save_to_sent_items},
        )


@register(SourceEnum.outlook)
class OutlookIntegration(SourceIntegrationInterface):

    async def client(self, data: Optional[OnboardingData] = None) -> GraphMailClient:
        """A mail client that writes back whatever it refreshes.

        Credentials handed in directly belong to a caller that has not stored them
        yet — onboarding — so those do not get persisted.
        """
        if data:
            return GraphMailClient(data)

        credentials = await self.get_credentials()
        return GraphMailClient(credentials, on_refresh=self.persist_tokens)


__all__ = [
    "DEFAULT_TIMEOUT",
    "FILE_ATTACHMENT_TYPE",
    "HTML_CONTENT",
    "SEND_MAIL_AS_MAILBOX",
    "SEND_MAIL_AS_USER",
    "TEXT_CONTENT",
    "DelegatedTokenExpired",
    "GraphMailClient",
    "OutlookIntegration",
    "build_message",
    "file_attachment",
    "recipient_list",
]
