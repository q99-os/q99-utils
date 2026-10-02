"""Fracttal OAuth lifecycle, read-only requests and complete asset pagination."""

import asyncio
import base64
from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.core.registry import get_integration_class
from q99_utils.integrations.sources.fracttal import ASSETS_URL, TOKEN_URL, FracttalIntegration
from q99_utils.models import OnboardingData


@pytest.fixture
def credentials():
    return OnboardingData(source=SourceEnum.fracttal, integration_type="external_api", client_id="application-key", client_secret="application-secret")


@pytest.fixture
def integration():
    return FracttalIntegration(source=SourceEnum.fracttal, um_sdk=AsyncMock())


@pytest.fixture
def install(monkeypatch):
    real_client = httpx.AsyncClient

    def use(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr("q99_utils.integrations.sources.fracttal.httpx.AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))

    return use


def token(value="token-1", expiry=7200):
    return httpx.Response(200, json={"access_token": value, "expires_in": expiry, "token_type": "Bearer"})


def assets(rows):
    return httpx.Response(200, json={"success": True, "data": rows, "total": len(rows)})


def test_registry():
    assert get_integration_class(SourceEnum.fracttal) is FracttalIntegration


async def test_wire_contract_empty_probe_and_client_closed(install, integration, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        return token() if request.method == "POST" else assets([])

    install(handler)
    async with integration.session(credentials) as session:
        assert await session.read_assets_page(limit=1) == []
        client = session._client
    assert client.is_closed
    auth, read = requests
    assert str(auth.url) == TOKEN_URL
    assert auth.headers["authorization"] == "Basic " + base64.b64encode(b"application-key:application-secret").decode()
    assert auth.content == b"grant_type=client_credentials"
    assert auth.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert str(read.url).split("?")[0] == ASSETS_URL
    assert read.headers["authorization"] == "Bearer token-1"
    assert dict(read.url.params) == {"start": "0", "limit": "1"}


async def test_connection_reads_one_asset(install, integration, credentials):
    install(lambda request: token() if request.method == "POST" else assets([]))
    await integration.test_connection(credentials)


async def test_stored_credentials_and_filters(install, integration, credentials):
    integration.credential_id = "credential-123"
    integration.um_sdk.get_credential.return_value = credentials.model_dump()

    def handler(request):
        if request.method == "POST":
            return token()
        assert dict(request.url.params) == {"start": "100", "limit": "5", "code": "A/1", "active": "false", "item_type": "2"}
        return assets([{"id": 1, "description": "raw asset", "custom_fields_values": None}])

    install(handler)
    assert await integration.read_assets_page(start=100, limit=5, filters={"code": "A/1", "active": False, "item_type": 2}) == [{"id": 1, "description": "raw asset", "custom_fields_values": None}]
    integration.um_sdk.get_credential.assert_awaited_once_with(credential_id="credential-123")


@pytest.mark.parametrize("missing", ["client_id", "client_secret"])
async def test_missing_credentials(integration, credentials, missing):
    setattr(credentials, missing, None)
    with pytest.raises(CredentialValidationError):
        await integration.read_assets_page(data=credentials)


@pytest.mark.parametrize("body", [{}, {"access_token": "", "expires_in": 7200, "token_type": "Bearer"}, {"access_token": "t", "expires_in": 0, "token_type": "Bearer"}, {"access_token": "t", "expires_in": "NaN", "token_type": "Bearer"}, {"access_token": "t", "expires_in": True, "token_type": "Bearer"}, {"access_token": "t", "expires_in": 7200, "token_type": "Basic"}])
async def test_invalid_tokens(install, integration, credentials, body):
    install(lambda request: httpx.Response(200, json=body))
    with pytest.raises(IntegrationError):
        await integration.read_assets_page(data=credentials)


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_oauth_rejection_is_safe(install, integration, credentials, status):
    install(lambda request: httpx.Response(status, text="application-secret leaked by upstream"))
    with pytest.raises(CredentialValidationError) as error:
        await integration.read_assets_page(data=credentials)
    assert "application-secret" not in str(error.value)


async def test_renewal_before_expiry_and_reuse(install, integration, credentials):
    issued = []
    headers = []

    def handler(request):
        if request.method == "POST":
            issued.append(len(issued) + 1)
            return token(f"token-{len(issued)}")
        headers.append(request.headers["authorization"])
        return assets([])

    install(handler)
    async with integration.session(credentials) as session:
        await session.read_assets_page()
        await session.read_assets_page()
        session._expires_at = 0
        await session.read_assets_page()
    assert len(issued) == 2
    assert headers == ["Bearer token-1", "Bearer token-1", "Bearer token-2"]


async def test_concurrent_401_renews_once(install, integration, credentials):
    first_reads = 0
    issued = 0
    barrier = asyncio.Event()

    async def handler(request):
        nonlocal first_reads, issued
        if request.method == "POST":
            issued += 1
            return token(f"token-{issued}")
        if request.headers["authorization"] == "Bearer token-1":
            first_reads += 1
            if first_reads == 2:
                barrier.set()
            await barrier.wait()
            return httpx.Response(401)
        return assets([])

    install(handler)
    async with integration.session(credentials) as session:
        assert await asyncio.gather(session.read_assets_page(), session.read_assets_page()) == [[], []]
    assert issued == 2


@pytest.mark.parametrize("status,expected_logins", [(401, 2), (403, 1)])
async def test_persistent_denial_is_bounded(install, integration, credentials, status, expected_logins):
    logins = []

    def handler(request):
        if request.method == "POST":
            logins.append(1)
            return token(f"token-{len(logins)}")
        return httpx.Response(status)

    install(handler)
    with pytest.raises(CredentialValidationError):
        await integration.read_assets_page(data=credentials)
    assert len(logins) == expected_logins


@pytest.mark.parametrize("body", [{"success": False, "data": []}, {"success": True, "data": {}}, {"success": True, "data": [1]}, [], {"success": True, "data": [{}, {}]}])
async def test_invalid_asset_response(install, integration, credentials, body):
    install(lambda request: token() if request.method == "POST" else httpx.Response(200, json=body))
    with pytest.raises(IntegrationError):
        await integration.read_assets_page(limit=1, data=credentials)


@pytest.mark.parametrize("on_token", [True, False])
async def test_non_json(install, integration, credentials, on_token):
    install(lambda request: httpx.Response(200, text="HTML") if on_token or request.method == "GET" else token())
    with pytest.raises(IntegrationError):
        await integration.read_assets_page(data=credentials)


@pytest.mark.parametrize("status", [429, 500])
async def test_http_error_is_not_retried(install, integration, credentials, status):
    reads = []

    def handler(request):
        if request.method == "POST":
            return token()
        reads.append(1)
        return httpx.Response(status)

    install(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await integration.read_assets_page(data=credentials)
    assert len(reads) == 1


async def test_full_pagination_ignores_page_total(install, integration, credentials):
    offsets = []

    def handler(request):
        if request.method == "POST":
            return token()
        start = int(request.url.params["start"])
        offsets.append(start)
        return assets([{"id": start + 1}, {"id": start + 2}] if start < 4 else [])

    install(handler)
    assert await integration.read_assets(limit=2, data=credentials) == [{"id": i} for i in range(1, 5)]
    assert offsets == [0, 2, 4]


@pytest.mark.parametrize("mode", ["repeated", "bounded", "later_failure", "timeout"])
async def test_full_read_never_returns_partial(install, integration, credentials, mode):
    def handler(request):
        if request.method == "POST":
            return token()
        start = int(request.url.params["start"])
        if start and mode == "later_failure":
            return httpx.Response(500)
        if start and mode == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        return assets([{"id": 1 if mode == "repeated" else start + 1}])

    install(handler)
    with pytest.raises((IntegrationError, httpx.HTTPError)):
        await integration.read_assets(limit=1, max_pages=2, data=credentials)


@pytest.mark.parametrize("kwargs", [{"start": -1}, {"start": True}, {"limit": 0}, {"limit": 101}, {"limit": False}, {"filters": {"limit": 1000}}, {"filters": {"unknown": "value"}}])
async def test_bad_parameters_fail_before_login(install, integration, credentials, kwargs):
    def handler(request):
        pytest.fail("Invalid parameters must not send credentials")

    install(handler)
    with pytest.raises(ValueError):
        await integration.read_assets_page(data=credentials, **kwargs)


async def test_probe_maps_transport_error_without_leaking(install, integration, credentials):
    install(lambda request: token() if request.method == "POST" else httpx.Response(500, text="application-secret"))
    with pytest.raises(CredentialValidationError) as error:
        await integration.test_connection(credentials)
    assert "application-secret" not in str(error.value)
