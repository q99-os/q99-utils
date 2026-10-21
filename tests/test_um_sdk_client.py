"""UserManagerSDK can share one HTTP client: an injected one is used and left to its owner."""

import httpx
import pytest

from q99_utils import um_sdk
from q99_utils.um_sdk import UserManagerSDK

UM_URL = "http://q99.user-manager.com:8000/um"
USER = {"id": 7, "email": "ana@cliente.com", "first_name": "Ana", "last_name": "Pérez"}


@pytest.fixture(autouse=True)
def user_manager_url(monkeypatch):
    monkeypatch.setattr(um_sdk, "USER_MANAGER_URL", UM_URL)


def recording_client(seen):
    def answer(request):
        seen.append(request)
        return httpx.Response(200, json=USER)

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def test_calls_go_through_the_injected_client():
    seen = []
    client = recording_client(seen)
    sdk = UserManagerSDK(access_token="token-ana", client=client)

    assert await sdk.get_current_user_info() == USER

    assert sdk.http_client is client
    assert [str(r.url) for r in seen] == [f"{UM_URL}/v1/user/info/"]
    assert seen[0].headers["Authorization"] == "token-ana"
    await client.aclose()


async def test_an_injected_client_is_left_open_for_its_owner():
    client = recording_client([])

    async with UserManagerSDK(api_key="key-engine", client=client) as sdk:
        await sdk.get_current_user_info()

    assert not client.is_closed
    await client.aclose()


async def test_without_a_client_the_sdk_opens_its_own_and_closes_it():
    sdk = UserManagerSDK(access_token="token-ana")
    own = sdk.http_client

    assert isinstance(own, httpx.AsyncClient)
    assert own.timeout == httpx.Timeout(30.0)
    await sdk.aclose()
    assert own.is_closed


async def test_two_sdks_share_one_client():
    client = recording_client([])
    caller = UserManagerSDK(access_token="token-ana", client=client)
    service = UserManagerSDK(api_key="key-engine", client=caller.http_client)

    assert service.http_client is caller.http_client
    await client.aclose()
