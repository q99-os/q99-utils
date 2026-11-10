"""Mirico's published bearer auth and authorized-site read contract."""

from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.core.registry import get_integration_class
from q99_utils.integrations.sources.mirico import DEFAULT_API_BASE, MiricoIntegration, STAGING_API_BASE
from q99_utils.models import OnboardingData


@pytest.fixture
def integration():
    return MiricoIntegration(source=SourceEnum.mirico, um_sdk=AsyncMock())


@pytest.fixture
def credentials():
    return OnboardingData(source=SourceEnum.mirico, integration_type="external_api", api_key="test-key")


@pytest.fixture
def install(monkeypatch):
    real_client = httpx.AsyncClient

    def use(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            "q99_utils.integrations.sources.mirico.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=transport, **kwargs),
        )

    return use


async def test_authorized_probe_and_read(install, integration, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/deployments/sites"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"id": 17, "fk_site_uuid": "site-1"}])

    install(handler)
    assert get_integration_class(SourceEnum.mirico) is MiricoIntegration
    await integration.test_connection(credentials)
    assert await integration.list_deployments(credentials) == [{"id": 17, "fk_site_uuid": "site-1"}]
    assert [str(req.url) for req in requests] == [
        f"{DEFAULT_API_BASE}/deployments/sites",
        f"{DEFAULT_API_BASE}/deployments/",
    ]
    assert all(req.headers["Authorization"] == "Bearer test-key" for req in requests)


async def test_staging_endpoint_can_be_set_internally(install, integration, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    install(handler)
    credentials.api_base = STAGING_API_BASE
    await integration.test_connection(credentials)
    assert str(requests[0].url) == f"{STAGING_API_BASE}/deployments/sites"


async def test_rejected_key_is_safe(install, integration, credentials):
    install(lambda request: httpx.Response(401, text="test-key must not appear in errors"))
    with pytest.raises(CredentialValidationError) as error:
        await integration.test_connection(credentials)
    assert "test-key" not in str(error.value)


async def test_invalid_url_is_rejected_before_request(integration, credentials):
    credentials.api_base = "http://localhost:8080/engine-api"
    with pytest.raises(CredentialValidationError, match="HTTPS"):
        await integration.test_connection(credentials)


async def test_unexpected_response_fails_probe(install, integration, credentials):
    install(lambda request: httpx.Response(200, json={"sites": []}))
    with pytest.raises(IntegrationError):
        await integration.list_sites(credentials)
    with pytest.raises(CredentialValidationError, match="connection test failed"):
        await integration.test_connection(credentials)
