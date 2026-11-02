"""Token refresh, push-notification watch and reading of the dedicated Gmail mailbox."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import AppCredentialExpired, CredentialExpired, IntegrationError
from q99_utils.integrations.sources.gmail_mailbox import GmailMailboxIntegration
from q99_utils.models import OnboardingData

TOKEN_URL = "https://oauth2.googleapis.com/token"


def _patch_transport(monkeypatch, *, token_response, gmail_responses=()) -> list:
    """Token refreshes get ``token_response``; Gmail API calls replay ``gmail_responses`` in order."""
    requested: list = []
    remaining = list(gmail_responses)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            requested.append({"method": "POST", "url": url, "data": kwargs.get("data")})
            status, payload = token_response
            return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

        async def request(self, method, url, **kwargs):
            requested.append({
                "method": method, "url": url, "json": kwargs.get("json"),
                "params": kwargs.get("params"), "headers": kwargs.get("headers"),
            })
            status, payload = remaining.pop(0)
            return httpx.Response(status, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return requested


@pytest.fixture
def integration() -> GmailMailboxIntegration:
    return GmailMailboxIntegration(source=SourceEnum.gmail_mailbox, um_sdk=None)


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.gmail_mailbox,
        client_id="client",
        client_secret="secret",
        refresh_token="refresh-1",
        mailbox_address="quantos@acme.com",
        pubsub_topic="projects/acme/topics/quantos-mail",
    )


async def test_get_access_token_uses_the_refresh_grant(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, token_response=(200, {"access_token": "fresh"}))

    assert await integration.get_access_token(credentials) == "fresh"
    assert requested[0]["data"]["grant_type"] == "refresh_token"
    assert requested[0]["data"]["refresh_token"] == "refresh-1"


async def test_gmail_token_invalid_client_raises_app_expired(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, token_response=(401, {"error": "invalid_client"}))

    with pytest.raises(AppCredentialExpired):
        await integration.get_access_token(credentials)


async def test_gmail_token_invalid_grant_raises_credential_expired(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, token_response=(400, {"error": "invalid_grant"}))

    with pytest.raises(CredentialExpired):
        await integration.get_access_token(credentials)


async def test_gmail_token_server_error_raises_integration_error(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, token_response=(503, {"error": "backendError"}))

    with pytest.raises(IntegrationError):
        await integration.get_access_token(credentials)


async def test_watch_sends_topic_and_inbox_label(monkeypatch, integration, credentials):
    requested = _patch_transport(
        monkeypatch,
        token_response=(200, {"access_token": "fresh"}),
        gmail_responses=[(200, {"historyId": "42", "expiration": "1762300800000"})],
    )

    result = await integration.watch(credentials)

    assert result == {"historyId": "42", "expiration": "1762300800000"}
    watch = requested[1]
    assert watch["url"] == "https://gmail.googleapis.com/gmail/v1/users/me/watch"
    assert watch["json"] == {
        "topicName": "projects/acme/topics/quantos-mail",
        "labelIds": ["INBOX"],
        "labelFilterBehavior": "include",
    }
    assert watch["headers"]["Authorization"] == "Bearer fresh"


async def test_stop_watch_calls_stop(monkeypatch, integration, credentials):
    requested = _patch_transport(
        monkeypatch,
        token_response=(200, {"access_token": "fresh"}),
        gmail_responses=[(204, None)],
    )

    assert await integration.stop_watch(credentials) is None
    assert requested[1]["url"] == "https://gmail.googleapis.com/gmail/v1/users/me/stop"


async def test_mailbox_address_comes_from_the_profile(monkeypatch, integration, credentials):
    requested = _patch_transport(
        monkeypatch,
        token_response=(200, {"access_token": "fresh"}),
        gmail_responses=[(200, {"emailAddress": "Quantos@Acme.com", "messagesTotal": 3})],
    )

    assert await integration.mailbox_address(credentials) == "quantos@acme.com"
    assert requested[1]["url"] == "https://gmail.googleapis.com/gmail/v1/users/me/profile"


# Reading the inbox


def _b64url(content: bytes) -> str:
    return base64.urlsafe_b64encode(content).decode()


async def test_gmail_lists_inbox_since_and_walks_nested_parts(monkeypatch, integration, credentials):
    full_message = {
        "id": "m1",
        "internalDate": "1793354400000",
        "payload": {"parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 4}},
            {"mimeType": "multipart/mixed", "filename": "", "parts": [
                {"mimeType": "application/pdf", "filename": "report.pdf",
                 "headers": [{"name": "Content-Disposition", "value": "attachment; filename=report.pdf"}],
                 "body": {"attachmentId": "a1", "size": 10}},
                {"mimeType": "image/png", "filename": "logo.png",
                 "headers": [{"name": "Content-Disposition", "value": "inline; filename=logo.png"}],
                 "body": {"attachmentId": "a2", "size": 5}},
            ]},
        ]},
    }
    requested = _patch_transport(
        monkeypatch,
        token_response=(200, {"access_token": "fresh"}),
        gmail_responses=[
            (200, {"messages": [{"id": "m1"}], "nextPageToken": "p2"}),
            (200, {"messages": []}),
            (200, full_message),
        ],
    )

    messages = await integration.list_inbox_messages(credentials, datetime(2026, 10, 29, tzinfo=timezone.utc))

    list_calls = [r for r in requested if r["url"].endswith("/users/me/messages")]
    assert list_calls[0]["params"]["q"] == "in:inbox after:1793232000"
    assert list_calls[1]["params"]["pageToken"] == "p2"
    assert [m.id for m in messages] == ["m1"]
    assert messages[0].received_at == datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    assert [(a.id, a.name, a.is_inline) for a in messages[0].attachments] == [
        ("a1", "report.pdf", False), ("a2", "logo.png", True),
    ]


async def test_gmail_download_decodes_base64url(monkeypatch, integration, credentials):
    requested = _patch_transport(
        monkeypatch,
        token_response=(200, {"access_token": "fresh"}),
        gmail_responses=[(200, {"data": _b64url(b"%PDF-1.7 \xff\xfe"), "size": 11})],
    )

    content = await integration.download_attachment("m1", "a1", credentials)

    assert content == b"%PDF-1.7 \xff\xfe"
    assert requested[1]["url"].endswith("/users/me/messages/m1/attachments/a1")


async def test_gmail_mark_processed_adds_label_and_removes_inbox(monkeypatch, integration, credentials):
    requested = _patch_transport(
        monkeypatch,
        token_response=(200, {"access_token": "fresh"}),
        gmail_responses=[
            (200, {"labels": [{"id": "INBOX", "name": "INBOX"}]}),
            (200, {"id": "Label_7", "name": "Quantos Processed"}),
            (200, {"id": "m1"}),
            (200, {"id": "m2"}),
        ],
    )

    await integration.mark_processed("m1", credentials)
    await integration.mark_processed("m2", credentials)

    api_calls = [r for r in requested if r["method"] != "POST" or "oauth2" not in r["url"]]
    assert [(r["method"], r["url"].rsplit("/", 2)[-2:]) for r in api_calls] == [
        ("GET", ["me", "labels"]),
        ("POST", ["me", "labels"]),
        ("POST", ["m1", "modify"]),
        ("POST", ["m2", "modify"]),
    ]
    assert api_calls[1]["json"]["name"] == "Quantos Processed"
    assert api_calls[2]["json"] == {"addLabelIds": ["Label_7"], "removeLabelIds": ["INBOX"]}
