"""The organizational Webex client rotates tokens and confines credentialed requests."""

from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import AppCredentialExpired, CredentialExpired
from q99_utils.integrations.sources.webex_client import WebexClient
from q99_utils.models import OnboardingData


@pytest.fixture
def credentials():
    return OnboardingData(
        source=SourceEnum.webex_archive, integration_type="file_system",
        api_key="old", refresh_token="refresh", client_id="app", client_secret="secret",
    )


@pytest.fixture
def install_transport(monkeypatch):
    real_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            "q99_utils.integrations.sources.webex_client.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


@pytest.mark.asyncio
async def test_expired_customer_token_rotates_and_persists(install_transport, credentials):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/v1/access_token":
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "rotated"})
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"items": []})

    install_transport(respond)
    persist = AsyncMock()
    client = WebexClient(credentials, on_refresh=persist)

    assert await client._json("/events", params={"max": 1}) == {"items": []}
    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    assert credentials.refresh_token == "rotated"
    persist.assert_awaited_once_with(credentials)


@pytest.mark.asyncio
async def test_customer_service_app_secret_refreshes_token(install_transport, credentials):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/v1/access_token":
            return httpx.Response(200, json={"access_token": "new"})
        return httpx.Response(200, json={"items": []})

    install_transport(respond)
    credentials.api_key = None
    assert await WebexClient(credentials)._json("/events") == {"items": []}
    assert requests[0].url.path == "/v1/access_token"
    assert "client_id=app" in requests[0].content.decode()
    assert "client_secret=secret" in requests[0].content.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("error, expected", [
    ("invalid_client", AppCredentialExpired),
    ("invalid_grant", CredentialExpired),
])
async def test_refresh_distinguishes_app_credentials_from_expired_token(
    install_transport, credentials, error, expected,
):
    install_transport(lambda request: httpx.Response(401, json={"error": error}))
    credentials.api_key = None

    with pytest.raises(expected):
        await WebexClient(credentials)._json("/events")


@pytest.mark.asyncio
async def test_refresh_uses_rotated_tokens_saved_by_another_worker(install_transport, credentials):
    def respond(request):
        if request.url.path == "/v1/access_token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if request.headers["Authorization"] == "Bearer rotated-access":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(401)

    install_transport(respond)
    reload_credentials = AsyncMock(return_value=credentials.model_copy(update={
        "api_key": "rotated-access", "refresh_token": "rotated-refresh",
    }))

    client = WebexClient(credentials, reload_credentials=reload_credentials)
    assert await client._json("/events") == {"items": []}
    reload_credentials.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_content_links_are_rejected_before_network(install_transport, credentials):
    requests = []
    install_transport(lambda request: requests.append(request) or httpx.Response(200))
    client = WebexClient(credentials)

    with pytest.raises(ValueError, match="Only supported Webex API"):
        await client.file_details("https://internal.example/secret")
    with pytest.raises(ValueError, match="Only Webex content"):
        await client.download("https://internal.example/secret", 1024)

    assert requests == []
