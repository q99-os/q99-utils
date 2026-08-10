"""Message building and delivery for Gmail and Outlook.

Both providers take the same attachment dicts from the caller and each turns
them into its own thing — a Graph JSON resource or a MIME tree — so a host can
build one list and hand it to either.
"""

from __future__ import annotations

import base64
import email

import httpx
import pytest

from q99_utils.integrations.sources.gmail import build_raw_message, header_join
from q99_utils.integrations.sources.outlook import (
    HTML_CONTENT,
    SEND_MAIL_AS_USER,
    TEXT_CONTENT,
    GraphMailClient,
    build_message,
    file_attachment,
    recipient_list,
)
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

ATTACHMENT = {"name": "note.txt", "content_b64": base64.b64encode(b"hola").decode()}


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.outlook,
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        api_key="stale-token",
        refresh_token="refresh-1",
    )


# Outlook payloads


def test_recipient_list_drops_blanks():
    assert recipient_list(["a@q99.ai", "", None]) == [
        {"emailAddress": {"address": "a@q99.ai"}}
    ]


def test_recipient_list_of_nothing_is_empty():
    assert recipient_list(None) == []


def test_message_carries_subject_body_and_recipients():
    message = build_message(subject="Hola", body="<b>hi</b>", to=["a@q99.ai"])

    assert message["subject"] == "Hola"
    assert message["body"] == {"contentType": HTML_CONTENT, "content": "<b>hi</b>"}
    assert message["toRecipients"] == [{"emailAddress": {"address": "a@q99.ai"}}]


def test_empty_optional_lists_are_left_out():
    """Graph reads an empty list as "clear these", so absent is not the same as []."""
    message = build_message(subject="s", body="b", to=["a@q99.ai"], cc=[], bcc=None)

    assert set(message) == {"subject", "body", "toRecipients"}


def test_optional_lists_appear_when_given():
    message = build_message(
        subject="s",
        body="b",
        to=["a@q99.ai"],
        cc=["c@q99.ai"],
        bcc=["b@q99.ai"],
        reply_to=["r@q99.ai"],
        attachments=[file_attachment(**ATTACHMENT)],
    )

    assert message["ccRecipients"] == [{"emailAddress": {"address": "c@q99.ai"}}]
    assert message["bccRecipients"] == [{"emailAddress": {"address": "b@q99.ai"}}]
    assert message["replyTo"] == [{"emailAddress": {"address": "r@q99.ai"}}]
    assert message["attachments"][0]["name"] == "note.txt"


def test_plain_text_body():
    message = build_message(
        subject="s", body="plano", to=["a@q99.ai"], content_type=TEXT_CONTENT
    )

    assert message["body"]["contentType"] == TEXT_CONTENT


def test_attachment_content_type_is_optional():
    assert "contentType" not in file_attachment(**ATTACHMENT)
    assert file_attachment(**ATTACHMENT, content_type="text/plain")["contentType"] == "text/plain"


# Gmail payloads


def test_header_join_drops_blanks():
    assert header_join(["a@q99.ai", "", "b@q99.ai"]) == "a@q99.ai, b@q99.ai"


def test_raw_message_is_decodable_mime_with_the_headers():
    raw = build_raw_message(
        subject="Hola",
        html="<b>hi</b>",
        to=["a@q99.ai"],
        cc=["c@q99.ai"],
        bcc=["b@q99.ai"],
    )
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))

    assert parsed["Subject"] == "Hola"
    assert parsed["To"] == "a@q99.ai"
    assert parsed["Cc"] == "c@q99.ai"
    assert parsed["Bcc"] == "b@q99.ai"


def test_raw_message_attaches_the_same_dict_outlook_takes():
    raw = build_raw_message(
        subject="s", html="<b>hi</b>", to=["a@q99.ai"], attachments=[ATTACHMENT]
    )
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))

    parts = [p for p in parsed.walk() if p.get_filename()]
    assert len(parts) == 1
    assert parts[0].get_filename() == "note.txt"
    assert parts[0].get_payload(decode=True) == b"hola"


def test_raw_message_keeps_the_html_part():
    raw = build_raw_message(subject="s", html="<b>hi</b>", to=["a@q99.ai"])
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))

    html = [p for p in parsed.walk() if p.get_content_type() == "text/html"]
    assert html and html[0].get_payload(decode=True) == b"<b>hi</b>"


# Delivery


def _patch_transport(monkeypatch, *, responses) -> list:
    """Replay ``responses`` for successive calls; record (method, url)."""
    calls: list = []
    remaining = list(responses)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            calls.append(("POST", url))
            status, payload = remaining.pop(0)
            return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return calls


def test_client_needs_an_access_token():
    with pytest.raises(ValueError):
        GraphMailClient(OnboardingData(source=SourceEnum.outlook))


async def test_send_mail_posts_as_the_signed_in_user(monkeypatch, credentials):
    calls = _patch_transport(monkeypatch, responses=[(202, None)])

    result = await GraphMailClient(credentials).send_mail(
        subject="s", html="<b>hi</b>", to=["a@q99.ai"]
    )

    assert result == {}
    assert calls[0][1].endswith(SEND_MAIL_AS_USER)


async def test_expired_token_is_refreshed_and_the_call_retried(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (401, {"error": "expired"}),
            (200, {"access_token": "fresh-token", "refresh_token": "refresh-2"}),
            (202, None),
        ],
    )
    client = GraphMailClient(credentials)

    await client.send_mail(subject="s", html="<b>hi</b>", to=["a@q99.ai"])

    assert len(calls) == 3
    assert "login.microsoftonline.com" in calls[1][1]
    assert client.access_token == "fresh-token"


async def test_a_rotated_refresh_token_is_kept(monkeypatch, credentials):
    _patch_transport(
        monkeypatch,
        responses=[
            (401, {"error": "expired"}),
            (200, {"access_token": "fresh-token", "refresh_token": "refresh-2"}),
            (202, None),
        ],
    )
    client = GraphMailClient(credentials)

    await client.send_mail(subject="s", html="<b>hi</b>", to=["a@q99.ai"])

    assert client.credentials.refresh_token == "refresh-2"


async def test_refresh_without_rotation_keeps_the_old_one(monkeypatch, credentials):
    _patch_transport(
        monkeypatch,
        responses=[
            (401, {"error": "expired"}),
            (200, {"access_token": "fresh-token"}),
            (202, None),
        ],
    )
    client = GraphMailClient(credentials)

    await client.send_mail(subject="s", html="<b>hi</b>", to=["a@q99.ai"])

    assert client.credentials.refresh_token == "refresh-1"
