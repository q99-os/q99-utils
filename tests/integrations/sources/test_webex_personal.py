from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import IntegrationTypeEnum, SourceEnum
from q99_utils.integrations.core import IntegrationContext
from q99_utils.integrations.sources.webex import WebexIntegration, WebexMessagingClient
from q99_utils.models import OnboardingData


@pytest.mark.asyncio
async def test_personal_webex_uses_company_oauth_integration():
    provider = AsyncMock()
    provider.app_credentials.return_value = {"client_id": "personal-app", "client_secret": "personal-secret"}
    integration = WebexIntegration(
        SourceEnum.webex, um_sdk=AsyncMock(), context=IntegrationContext(company_app=provider)
    )
    credentials = OnboardingData(
        source=SourceEnum.webex, integration_type=IntegrationTypeEnum.bot,
        api_key="user-token", refresh_token="user-refresh",
        client_id="old-app", client_secret="old-secret",
    )

    client = await integration.client(credentials)

    provider.app_credentials.assert_awaited_once_with("webex_archive")
    assert client.credentials.client_id == "personal-app"
    assert client.credentials.client_secret == "personal-secret"
    assert credentials.client_id == "old-app"


@pytest.mark.asyncio
async def test_webex_post_uses_personal_token_and_one_destination(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "m1", "roomId": "r1"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "q99_utils.integrations.sources.webex_client.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    client = WebexMessagingClient(OnboardingData(
        source=SourceEnum.webex, integration_type=IntegrationTypeEnum.bot,
        api_key="user-token", refresh_token="user-refresh",
    ), source="webex")

    result = await client.send("Hello", room_id="r1")

    assert result == {"id": "m1", "room_id": "r1"}
    assert calls[0].headers["Authorization"] == "Bearer user-token"
    assert calls[0].read().decode().find('"roomId":"r1"') >= 0
    with pytest.raises(ValueError):
        await client.send(" ", room_id="r1")
    with pytest.raises(ValueError):
        await client.send("Hello", room_id="r1", email="someone@example.com")
    assert len(calls) == 1
