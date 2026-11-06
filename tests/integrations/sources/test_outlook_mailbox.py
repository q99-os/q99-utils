"""Subscriptions on, and reading of, the dedicated Outlook mailbox."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import (
    AccessDenied,
    CredentialExpired,
    CredentialValidationError,
    IntegrationError,
    get_integration_class,
    graph_request,
)
from q99_utils.integrations.sources.outlook_mailbox import OutlookMailboxIntegration
from q99_utils.models import OnboardingData


def _patch_transport(monkeypatch, *, responses) -> list:
    """Answer token POSTs automatically and replay ``responses`` for Graph calls."""
    requested: list = []
    remaining = list(responses)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            return httpx.Response(200, json={"access_token": "tok"}, request=httpx.Request("POST", url))

        async def request(self, method, url, **kwargs):
            requested.append({"method": method, "url": url, "json": kwargs.get("json")})
            status, payload = remaining.pop(0)
            return httpx.Response(status, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return requested


@pytest.fixture
def integration() -> OutlookMailboxIntegration:
    return OutlookMailboxIntegration(source=SourceEnum.outlook_mailbox, um_sdk=None)


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.outlook_mailbox,
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        mailbox_address="quantos@acme.com",
    )


def test_mailbox_sources_are_registered():
    from q99_utils.integrations.sources.gmail_mailbox import GmailMailboxIntegration

    assert get_integration_class(SourceEnum.outlook_mailbox) is OutlookMailboxIntegration
    assert get_integration_class(SourceEnum.gmail_mailbox) is GmailMailboxIntegration


async def test_create_subscription_watches_the_inbox(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[(201, {"id": "sub-1"})])

    result = await integration.create_subscription(
        notification_url="https://q99.ai/um/v1/mailbox/webhook/outlook/",
        client_state="state",
        expiration="2026-11-04T00:00:00Z",
        data=credentials,
    )

    assert result == {"id": "sub-1"}
    body = requested[0]["json"]
    assert requested[0]["method"] == "POST"
    assert body["resource"] == "/users/quantos@acme.com/mailFolders('Inbox')/messages"
    assert body["changeType"] == "created"
    assert body["clientState"] == "state"
    assert body["lifecycleNotificationUrl"] == body["notificationUrl"]


async def test_renew_subscription_patches_the_expiration(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[(200, {"id": "sub-1"})])

    await integration.renew_subscription("sub-1", "2026-11-10T00:00:00Z", credentials)

    assert requested[0]["method"] == "PATCH"
    assert requested[0]["url"].endswith("/subscriptions/sub-1")
    assert requested[0]["json"] == {"expirationDateTime": "2026-11-10T00:00:00Z"}


async def test_delete_subscription_tolerates_an_empty_body(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[(204, None)])

    assert await integration.delete_subscription("sub-1", credentials) is None
    assert requested[0]["method"] == "DELETE"


# Onboarding probe


async def test_test_connection_reads_the_mailbox_inbox(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[(200, {"id": "inbox", "displayName": "Inbox"})])

    await integration.test_connection(credentials)

    assert requested[0]["url"].endswith("/users/quantos@acme.com/mailFolders/inbox")


async def test_test_connection_explains_a_refused_mailbox(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, responses=[(403, {"error": {"code": "ErrorAccessDenied"}})])

    with pytest.raises(CredentialValidationError) as refused:
        await integration.test_connection(credentials)

    message = str(refused.value)
    assert "Microsoft Service" in message and "Mail.ReadWrite" in message and "Access Policy" in message
    assert "tenant_id" not in message  # the admin no longer types the app's keys


# Reading the inbox


async def test_outlook_lists_inbox_since_and_keeps_file_attachments(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[
        (200, {"value": [{"id": "m1", "receivedDateTime": "2026-10-30T10:00:00Z"}]}),
        (200, {"value": [
            {"@odata.type": "#microsoft.graph.fileAttachment", "id": "a1", "name": "report.pdf",
             "contentType": "application/pdf", "size": 10, "isInline": False},
            {"@odata.type": "#microsoft.graph.fileAttachment", "id": "a2", "name": "logo.png",
             "contentType": "image/png", "size": 5, "isInline": True},
            {"@odata.type": "#microsoft.graph.itemAttachment", "id": "a3", "name": "fwd",
             "contentType": None, "size": 7, "isInline": False},
        ]}),
    ])

    messages = await integration.list_inbox_messages(credentials, datetime(2026, 10, 29, tzinfo=timezone.utc))

    assert "receivedDateTime ge 2026-10-29T00:00:00Z" in unquote(requested[0]["url"])
    assert "/users/quantos@acme.com/mailFolders/inbox/messages" in requested[0]["url"]
    assert [m.id for m in messages] == ["m1"]
    assert messages[0].received_at == datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    assert [(a.id, a.name, a.is_inline) for a in messages[0].attachments] == [
        ("a1", "report.pdf", False), ("a2", "logo.png", True),
    ]


@pytest.mark.parametrize("status", [401, 403])
async def test_outlook_mailbox_access_revoked_is_an_expired_credential(monkeypatch, integration, credentials, status):
    # The token still comes back; only the mailbox refuses (consent removed, access policy changed).
    _patch_transport(monkeypatch, responses=[(status, {"error": {"code": "ErrorAccessDenied"}})])

    with pytest.raises(CredentialExpired) as raised:
        await integration.list_inbox_messages(credentials, datetime(2026, 10, 29, tzinfo=timezone.utc))

    assert raised.value.source == str(SourceEnum.outlook_mailbox)


async def test_graph_access_denied_is_still_an_integration_error(monkeypatch):
    _patch_transport(monkeypatch, responses=[(403, {})])

    with pytest.raises(AccessDenied) as raised:
        await graph_request(access_token="tok", url="https://graph.microsoft.com/v1.0/sites/s1")

    assert isinstance(raised.value, IntegrationError)
    assert "failed with 403" in str(raised.value)


async def test_outlook_download_decodes_content_bytes(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[
        (200, {"contentBytes": base64.b64encode(b"%PDF-1.7").decode()}),
    ])

    content = await integration.download_attachment("m1", "a1", credentials)

    assert content == b"%PDF-1.7"
    assert requested[0]["url"].endswith("/users/quantos@acme.com/messages/m1/attachments/a1")


async def test_outlook_mark_processed_creates_folder_once_and_moves(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, responses=[
        (200, {"value": []}),
        (201, {"id": "folder-1"}),
        (201, {"id": "m1-moved"}),
        (201, {"id": "m2-moved"}),
    ])

    await integration.mark_processed("m1", credentials)
    await integration.mark_processed("m2", credentials)

    assert [r["method"] for r in requested] == ["GET", "POST", "POST", "POST"]
    assert "displayName eq 'Quantos Processed'" in unquote(requested[0]["url"])
    assert requested[1]["json"] == {"displayName": "Quantos Processed"}
    assert requested[2]["url"].endswith("/messages/m1/move")
    assert requested[2]["json"] == {"destinationId": "folder-1"}
    assert requested[3]["url"].endswith("/messages/m2/move")
