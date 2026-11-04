"""Outlook mailbox integration — the dedicated company inbox whose attachments are ingested.

App-only, through an app registration the client restricts to that one mailbox.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import (
    GRAPH_BASE_URL,
    PROCESSED_FOLDER,
    AccessDenied,
    CredentialExpired,
    CredentialValidationError,
    MailAttachment,
    MailboxIntegration,
    MailMessage,
    MicrosoftGraphAuth,
    graph_paginate,
    graph_request,
    register,
)
from q99_utils.models import OnboardingData

GRAPH_SUBSCRIPTIONS_URL = f"{GRAPH_BASE_URL}/subscriptions"
FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"


def _query(params: Dict[str, str]) -> str:
    # Graph wants spaces as %20 and the $ of its query options left as is.
    return urlencode(params, quote_via=quote, safe="$,'")


@register(SourceEnum.outlook_mailbox)
class OutlookMailboxIntegration(MicrosoftGraphAuth, MailboxIntegration):

    _processed_folder_id: Optional[str] = None

    async def test_connection(self, data: OnboardingData) -> None:
        """The app can get a token and open the mailbox's inbox."""
        try:
            token = await self.get_access_token(data)
            await graph_request(
                access_token=token, url=f"{GRAPH_BASE_URL}/users/{data.mailbox_address}/mailFolders/inbox"
            )
        except Exception as exc:
            raise CredentialValidationError(
                f"Could not open the inbox of {data.mailbox_address}. Check tenant_id, client_id and "
                "client_secret, and that the app has the Mail.ReadWrite application permission "
                "(admin-consented) for that mailbox.",
                source=str(self.source),
            ) from exc

    # Reading the inbox

    async def list_inbox_messages(self, data: OnboardingData, received_after: datetime) -> List[MailMessage]:
        token = await self.get_access_token(data)
        mailbox_url = f"{GRAPH_BASE_URL}/users/{data.mailbox_address}"
        since = received_after.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = _query({"$filter": f"receivedDateTime ge {since}", "$select": "id,receivedDateTime"})

        messages = []
        try:
            async for item in graph_paginate(access_token=token, url=f"{mailbox_url}/mailFolders/inbox/messages?{query}"):
                attachments_query = _query({"$select": "id,name,contentType,size,isInline"})
                attachments = await graph_request(
                    access_token=token, url=f"{mailbox_url}/messages/{item['id']}/attachments?{attachments_query}"
                )
                messages.append(MailMessage(
                    id=item["id"],
                    received_at=datetime.fromisoformat(item["receivedDateTime"]),
                    # Attached emails and cloud links have no bytes to ingest.
                    attachments=[
                        MailAttachment(
                            id=a["id"],
                            name=a.get("name") or "",
                            content_type=a.get("contentType") or "",
                            size=a.get("size") or 0,
                            is_inline=bool(a.get("isInline")),
                        )
                        for a in attachments.get("value") or []
                        if a.get("@odata.type") == FILE_ATTACHMENT
                    ],
                ))
        except AccessDenied as exc:
            # The app still gets a token but may no longer read the mailbox: only the admin can fix it.
            raise CredentialExpired(
                f"The app can no longer read {data.mailbox_address}: {exc}", source=str(self.source)
            ) from exc
        return messages

    async def download_attachment(self, message_id: str, attachment_id: str, data: OnboardingData) -> bytes:
        token = await self.get_access_token(data)
        attachment = await graph_request(
            access_token=token,
            url=f"{GRAPH_BASE_URL}/users/{data.mailbox_address}/messages/{message_id}/attachments/{attachment_id}",
        )
        return base64.b64decode(attachment["contentBytes"])

    async def mark_processed(self, message_id: str, data: OnboardingData) -> None:
        token = await self.get_access_token(data)
        mailbox_url = f"{GRAPH_BASE_URL}/users/{data.mailbox_address}"

        if self._processed_folder_id is None:
            query = _query({"$filter": f"displayName eq '{PROCESSED_FOLDER}'"})
            found = await graph_request(access_token=token, url=f"{mailbox_url}/mailFolders?{query}")
            folders = found.get("value") or []
            if folders:
                self._processed_folder_id = folders[0]["id"]
            else:
                created = await graph_request(
                    access_token=token, url=f"{mailbox_url}/mailFolders", method="POST",
                    json={"displayName": PROCESSED_FOLDER},
                )
                self._processed_folder_id = created["id"]

        await graph_request(
            access_token=token, url=f"{mailbox_url}/messages/{message_id}/move", method="POST",
            json={"destinationId": self._processed_folder_id},
        )

    # Change notifications

    async def create_subscription(
        self,
        *,
        notification_url: str,
        client_state: str,
        expiration: str,
        data: OnboardingData,
    ) -> Dict[str, Any]:
        """Be notified of every new message in the mailbox's inbox."""
        token = await self.get_access_token(data)
        payload = {
            "changeType": "created",
            "resource": f"/users/{data.mailbox_address}/mailFolders('Inbox')/messages",
            "notificationUrl": notification_url,
            "lifecycleNotificationUrl": notification_url,
            "expirationDateTime": expiration,
            "clientState": client_state,
        }
        return await graph_request(
            access_token=token, url=GRAPH_SUBSCRIPTIONS_URL, method="POST", json=payload
        )

    async def renew_subscription(
        self, subscription_id: str, expiration: str, data: OnboardingData
    ) -> Dict[str, Any]:
        token = await self.get_access_token(data)
        return await graph_request(
            access_token=token,
            url=f"{GRAPH_SUBSCRIPTIONS_URL}/{subscription_id}",
            method="PATCH",
            json={"expirationDateTime": expiration},
        )

    async def delete_subscription(self, subscription_id: str, data: OnboardingData) -> None:
        token = await self.get_access_token(data)
        await graph_request(
            access_token=token,
            url=f"{GRAPH_SUBSCRIPTIONS_URL}/{subscription_id}",
            method="DELETE",
        )


__all__ = ["OutlookMailboxIntegration"]
