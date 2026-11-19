"""Webex reads use delegated credentials and stay within bounded live access."""

from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.registry import get_integration_class
from q99_utils.integrations.sources.webex import WebexClient, WebexIntegration
from q99_utils.models import OnboardingData


@pytest.fixture
def credentials():
    return OnboardingData(
        source=SourceEnum.webex, integration_type="bot", api_key="old",
        refresh_token="refresh", client_id="app", client_secret="secret",
    )


@pytest.fixture
def install(monkeypatch):
    real_client = httpx.AsyncClient

    def use(handler):
        monkeypatch.setattr(
            "q99_utils.integrations.sources.webex.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )

    return use


async def test_connection_checks_current_user_only(install, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "person-1"})

    install(handler)
    integration = WebexIntegration(source=SourceEnum.webex, um_sdk=AsyncMock())
    assert get_integration_class(SourceEnum.webex) is WebexIntegration
    await integration.test_connection(credentials)
    assert [(r.method, str(r.url)) for r in requests] == [
        ("GET", "https://webexapis.com/v1/people/me")
    ]


async def test_expired_access_token_refreshes_once_and_persists_rotation(install, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/v1/access_token":
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "rotated"})
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"id": "person-1"})

    install(handler)
    saved = AsyncMock()
    client = WebexClient(credentials, on_refresh=saved)
    assert (await client.me())["id"] == "person-1"
    assert [r.method for r in requests] == ["GET", "POST", "GET"]
    assert credentials.refresh_token == "rotated"
    saved.assert_awaited_once_with(credentials)


async def test_live_search_reports_partial_coverage(install, credentials):
    def handler(request):
        if request.url.path == "/v1/rooms":
            return httpx.Response(200, json={"items": [{"id": "one"}, {"id": "two"}]})
        room_id = request.url.params["roomId"]
        return httpx.Response(200, json={"items": [{"id": room_id, "text": "Project alpha"}]})

    install(handler)
    result = await WebexClient(credentials).search_messages("alpha", limit=1)
    assert [item["id"] for item in result["messages"]] == ["one"]
    assert result["spaces_searched"] == 1
    assert result["partial"] is True


async def test_meeting_resources_use_read_endpoints(install, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    install(handler)
    client = WebexClient(credentials)
    assert await client.recordings("meeting-1") == []
    assert await client.transcripts("meeting-1") == []
    assert await client.summary("meeting-1") == []
    assert [r.url.path for r in requests] == [
        "/v1/recordings", "/v1/meetingTranscripts", "/v1/meetingSummaries",
    ]
    assert all(r.url.params["meetingId"] == "meeting-1" for r in requests)


async def test_transcript_download_rejects_untrusted_url(install, credentials):
    def handler(request):
        return httpx.Response(200, json={
            "items": [{"id": "t", "txtDownloadLink": "https://evil.example/private"}],
        })

    install(handler)
    with pytest.raises(ValueError, match="Only Webex API"):
        await WebexClient(credentials).transcripts("meeting-1", include_text=True)
