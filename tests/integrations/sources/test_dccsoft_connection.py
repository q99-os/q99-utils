"""Datawell and Wellprod validate only their API connection."""

from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError
from q99_utils.integrations.core.registry import get_integration_class
from q99_utils.integrations.sources import DatawellIntegration, WellprodIntegration
from q99_utils.models import OnboardingData


@pytest.fixture
def install(monkeypatch):
    real_client = httpx.AsyncClient

    def use(handler):
        monkeypatch.setattr(
            "q99_utils.integrations.sources.dccsoft_connection.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )

    return use


@pytest.mark.parametrize("source,cls,base", [
    (SourceEnum.datawell, DatawellIntegration, "https://other.example.com/rest"),
    (SourceEnum.wellprod, WellprodIntegration, "https://another.example.com/wp-rest"),
])
async def test_connection_uses_only_login_at_configured_installation(install, source, cls, base):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"token": "jwt"})

    install(handler)
    integration = cls(source=source, um_sdk=AsyncMock())
    data = OnboardingData(source=source, integration_type="external_api", api_base=base, username="reader", password="secret")

    assert get_integration_class(source) is cls
    await integration.test_connection(data)
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == f"{base}/api/auth/login"
    assert requests[0].content == b'{"username":"reader","password":"secret"}'


@pytest.mark.parametrize("response", [
    httpx.Response(401, text="secret leaked upstream"),
    httpx.Response(403, text="secret leaked upstream"),
    httpx.Response(200, json={}),
    httpx.Response(200, text="not json"),
    httpx.Response(500, text="secret leaked upstream"),
])
async def test_connection_failure_is_sanitized(install, response):
    install(lambda request: response)
    data = OnboardingData(
        source=SourceEnum.datawell, integration_type="external_api", api_base="https://example.com/rest", username="reader", password="secret",
    )
    integration = DatawellIntegration(source=SourceEnum.datawell, um_sdk=AsyncMock())

    with pytest.raises(CredentialValidationError) as error:
        await integration.test_connection(data)
    assert "secret" not in str(error.value)


async def test_missing_credentials_do_not_call_api(install):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    integration = WellprodIntegration(source=SourceEnum.wellprod, um_sdk=AsyncMock())
    data = OnboardingData(source=SourceEnum.wellprod, integration_type="external_api", api_base="https://example.com/wp-rest", username="", password="")

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(data)
    assert requests == []


@pytest.mark.parametrize("bad_url", [None, "", "http://example.com/rest", "https://user:pass@example.com/rest", "https://example.com/rest?token=x", "https://example.com/rest#private"])
async def test_invalid_api_base_does_not_call_api(install, bad_url):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    integration = DatawellIntegration(source=SourceEnum.datawell, um_sdk=AsyncMock())
    data = OnboardingData(source=SourceEnum.datawell, integration_type="external_api", api_base=bad_url, username="reader", password="secret")

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(data)
    assert requests == []


async def test_swagger_url_is_accepted_as_api_base(install):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    integration = WellprodIntegration(source=SourceEnum.wellprod, um_sdk=AsyncMock())
    for url in (
        "https://another.example.com/wp-rest/swagger-ui/index.html",
        "https://another.example.com/wp-rest/swagger-ui/index.html#/",
    ):
        data = OnboardingData(
            source=SourceEnum.wellprod, integration_type="external_api",
            api_base=url, username="reader", password="secret",
        )
        await integration.test_connection(data)

    assert [str(request.url) for request in requests] == [
        "https://another.example.com/wp-rest/api/auth/login",
        "https://another.example.com/wp-rest/api/auth/login",
    ]


@pytest.mark.parametrize("source,wrong_path,expected_path", [
    (SourceEnum.datawell, "/wp-rest", "/rest"),
    (SourceEnum.wellprod, "/rest", "/wp-rest"),
    (SourceEnum.datawell, "/rest/wrong", "/rest"),
])
async def test_other_product_or_path_is_rejected_before_login(install, source, wrong_path, expected_path):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    integration = (DatawellIntegration if source == SourceEnum.datawell else WellprodIntegration)(
        source=source, um_sdk=AsyncMock(),
    )
    data = OnboardingData(
        source=source, integration_type="external_api",
        api_base=f"https://other.example.com{wrong_path}",
        username="reader", password="secret",
    )

    with pytest.raises(CredentialValidationError, match=f"must end in {expected_path}"):
        await integration.test_connection(data)
    assert requests == []


async def test_datawell_swagger_url_with_trailing_hash_is_accepted(install):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    data = OnboardingData(
        source=SourceEnum.datawell, integration_type="external_api",
        api_base="https://other.example.com/rest/swagger-ui/index.html#",
        username="reader", password="secret",
    )

    await DatawellIntegration(source=SourceEnum.datawell, um_sdk=AsyncMock()).test_connection(data)
    assert [str(request.url) for request in requests] == ["https://other.example.com/rest/api/auth/login"]
