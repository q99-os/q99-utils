from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import IntegrationContext
from q99_utils.integrations.ports.files import IndexedFile
from q99_utils.integrations.sources.webex_archive import WebexArchiveIntegration, UNMAPPED
from q99_utils.models import PermissionTokens


def integration(known=None):
    store = AsyncMock()
    store.indexed_files.return_value = known or {}
    item = WebexArchiveIntegration(
        source=SourceEnum.webex_archive, um_sdk=AsyncMock(),
        context=IntegrationContext(file_store=store),
    )
    item.credential_id = "company-credential"
    item.load_sync_cursors = AsyncMock(return_value={})
    return item


def page(items, next_url=None):
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return httpx.Response(200, json={"items": items}, headers=headers)


@pytest.mark.asyncio
async def test_attachment_discovery_uses_room_membership_not_message_text():
    item = integration()
    client = AsyncMock()
    client._request.side_effect = [
        page([{
            "resource": "messages", "type": "created", "created": "2026-11-20T10:00:00Z",
            "data": {"id": "m1", "roomId": "r1", "text": "Do not index this text"},
        }]),
        page([{"personEmail": "alice@example.com"}, {"personEmail": "bob@example.com"}]),
    ]
    client._json.return_value = {"files": ["https://webexapis.com/v1/contents/f1"]}
    client.file_details.return_value = {
        "content_disposition": 'attachment; filename="inspection.pdf"',
        "content_length": "1024", "content_type": "application/pdf",
    }
    item.client = AsyncMock(return_value=client)
    found, cursor = await item.files_discovery()
    assert len(found) == 1
    assert found[0].name == "inspection.pdf"
    assert found[0].permissions == [
        PermissionTokens.email("alice@example.com"),
        PermissionTokens.email("bob@example.com"),
    ]
    assert "Do not index this text" not in found[0].model_dump_json()
    assert "webex_events_from" in cursor


@pytest.mark.asyncio
async def test_missing_membership_fails_closed():
    item = integration()
    client = AsyncMock()
    client._request.side_effect = [
        page([{"resource": "messages", "type": "created", "data": {"id": "m1", "roomId": "r1"}}]),
        page([]),
    ]
    client._json.return_value = {"files": ["https://webexapis.com/v1/contents/f1"]}
    client.file_details.return_value = {
        "content_disposition": 'attachment; filename="a.pdf"', "content_length": "50",
    }
    item.client = AsyncMock(return_value=client)
    found, _ = await item.files_discovery()
    assert found[0].permissions == [UNMAPPED]


@pytest.mark.asyncio
async def test_membership_removal_updates_existing_file_permissions():
    ref = "room/r1/message/m1/attachment/https%3A%2F%2Fwebexapis.com%2Fv1%2Fcontents%2Ff1"
    item = integration({ref: IndexedFile(None, None, [PermissionTokens.email("alice@example.com")])})
    client = AsyncMock()
    client._request.side_effect = [
        page([{"resource": "memberships", "type": "deleted", "data": {"roomId": "r1"}}]),
        page([]),
    ]
    item.client = AsyncMock(return_value=client)
    found, _ = await item.files_discovery()
    assert len(found) == 1
    assert found[0].change_kind == "permissions_changed"
    assert found[0].permissions == [UNMAPPED]


@pytest.mark.asyncio
async def test_transcript_is_host_only_and_noise_is_cleaned():
    item = integration()
    client = AsyncMock()
    client._request.return_value = page([{
        "resource": "meetingTranscripts", "type": "created", "created": "2026-11-20T10:00:00Z",
        "data": {"id": "t1", "meetingId": "meeting1", "hostEmail": "Host@Example.com"},
    }])
    client.download.return_value = b"WEBVTT\n\nAlice: We approved the inspection plan.\nAlice: We approved the inspection plan.\nBob: I will send the report tomorrow."
    item.client = AsyncMock(return_value=client)
    found, _ = await item.files_discovery()
    assert len(found) == 1
    assert found[0].permissions == ["email:host@example.com"]
    assert found[0].mime_type == "text/plain"
    client.download.assert_awaited_once_with(
        "https://webexapis.com/v1/meetingTranscripts/t1/download?format=txt", 5 * 1024 * 1024,
    )


@pytest.mark.asyncio
async def test_paginated_window_keeps_next_link_for_later_run():
    item = integration()
    client = AsyncMock()
    client._request.side_effect = [
        page([], "https://webexapis.com/v1/events?after=page2"),
        page([], "https://webexapis.com/v1/events?after=page3"),
    ]
    item.client = AsyncMock(return_value=client)
    _, cursor = await item.files_discovery()
    assert cursor["webex_events_next"] == "https://webexapis.com/v1/events?after=page3"
    assert cursor["webex_events_to"]


@pytest.mark.asyncio
async def test_deleted_message_stays_suppressed_across_partial_windows():
    item = integration()
    item.load_sync_cursors = AsyncMock(return_value={
        "webex_events_next": "https://webexapis.com/v1/events?after=page3",
        "webex_events_from": "2026-11-01T00:00:00Z",
        "webex_events_to": "2026-11-20T00:00:00Z",
        "webex_deleted_messages": ["room/r1/message/m1/attachment/"],
    })
    client = AsyncMock()
    client._request.return_value = page([{
        "resource": "messages", "type": "created",
        "data": {"id": "m1", "roomId": "r1"},
    }])
    client._json.return_value = {"files": ["https://webexapis.com/v1/contents/f1"]}
    client.file_details.return_value = {
        "content_disposition": 'attachment; filename="a.pdf"', "content_length": "50",
    }
    item.client = AsyncMock(return_value=client)
    found, cursor = await item.files_discovery()
    assert found == []
    assert "webex_deleted_messages" not in cursor
