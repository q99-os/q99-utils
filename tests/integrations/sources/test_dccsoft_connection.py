"""Datawell and Wellprod: the connection test and reading a view."""

from unittest.mock import AsyncMock

import httpx
import pytest

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
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
    assert str(error.value).startswith("Datawell ")


async def test_missing_credentials_do_not_call_api(install):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    integration = WellprodIntegration(source=SourceEnum.wellprod, um_sdk=AsyncMock())
    data = OnboardingData(source=SourceEnum.wellprod, integration_type="external_api", api_base="https://example.com/wp-rest", username="", password="")

    with pytest.raises(CredentialValidationError, match="^Wellprod "):
        await integration.test_connection(data)
    assert requests == []


@pytest.mark.parametrize("bad_url", [None, "", "http://example.com/rest", "https://user:pass@example.com/rest", "https://example.com/rest?token=x", "https://example.com/rest#private"])
async def test_invalid_api_base_does_not_call_api(install, bad_url):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    integration = DatawellIntegration(source=SourceEnum.datawell, um_sdk=AsyncMock())
    data = OnboardingData(source=SourceEnum.datawell, integration_type="external_api", api_base=bad_url, username="reader", password="secret")

    with pytest.raises(CredentialValidationError, match="^Datawell "):
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


@pytest.mark.parametrize("source,wrong_path", [
    (SourceEnum.datawell, "/wp-rest"),
    (SourceEnum.wellprod, "/rest"),
    (SourceEnum.datawell, "/rest/wrong"),
    (SourceEnum.wellprod, "/test"),
])
async def test_other_product_or_path_is_rejected_before_login(install, source, wrong_path):
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

    with pytest.raises(CredentialValidationError, match=f"^Enter your company URL without an extra path, or paste the {source.capitalize()} Swagger URL"):
        await integration.test_connection(data)
    assert requests == []


@pytest.mark.parametrize("source,cls,api_path", [
    (SourceEnum.datawell, DatawellIntegration, "/rest"),
    (SourceEnum.wellprod, WellprodIntegration, "/wp-rest"),
])
async def test_company_url_adds_product_path_before_login(install, source, cls, api_path):
    requests = []
    install(lambda request: requests.append(request) or httpx.Response(200, json={"token": "jwt"}))
    data = OnboardingData(
        source=source, integration_type="external_api",
        api_base="https://business.example.com/", username="reader", password="secret",
    )

    await cls(source=source, um_sdk=AsyncMock()).test_connection(data)
    assert [str(request.url) for request in requests] == [
        f"https://business.example.com{api_path}/api/auth/login"
    ]


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


def _reader(source=SourceEnum.wellprod):
    cls = WellprodIntegration if source == SourceEnum.wellprod else DatawellIntegration
    api_base = "https://example.com/wp-rest" if source == SourceEnum.wellprod else "https://example.com/rest"
    data = OnboardingData(source=source, integration_type="external_api", api_base=api_base, username="reader", password="secret")
    return cls(source=source, um_sdk=AsyncMock()), data


async def test_read_view_pages_until_a_short_page(install):
    requests = []
    pages = {"0": [{"pozo": "A"}, {"pozo": "B"}], "1": [{"pozo": "C"}, {"pozo": "D"}], "2": [{"pozo": "E"}]}

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"token": "jwt"})
        return httpx.Response(200, json=pages[request.url.params["page"]])

    install(handler)
    integration, data = _reader()

    rows = await integration.read_view("q99_wells", data, page_size=2)

    assert [r["pozo"] for r in rows] == ["A", "B", "C", "D", "E"]
    gets = [r for r in requests if r.method == "GET"]
    assert [r.url.path for r in gets] == ["/wp-rest/api/vistas/q99_wells/pagina"] * 3
    assert [r.url.params["size"] for r in gets] == ["2"] * 3
    assert all(r.headers["Authorization"] == "Bearer jwt" for r in gets)
    assert all(r.method in ("POST", "GET") for r in requests)


async def test_read_view_logs_in_again_once_when_the_token_expires(install):
    logins = []
    tokens_seen = []

    def handler(request):
        if request.method == "POST":
            logins.append(request)
            return httpx.Response(200, json={"token": f"jwt{len(logins)}"})
        tokens_seen.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer jwt1":
            return httpx.Response(401)
        return httpx.Response(200, json=[{"pozo": "A"}])

    install(handler)
    integration, data = _reader()

    assert await integration.read_view("q99_wells", data) == [{"pozo": "A"}]
    assert len(logins) == 2
    assert tokens_seen == ["Bearer jwt1", "Bearer jwt2"]


async def test_read_view_denied_after_logging_in_again_is_a_credential_error(install):
    install(lambda request: httpx.Response(200, json={"token": "jwt"}) if request.method == "POST" else httpx.Response(401))
    integration, data = _reader()

    with pytest.raises(CredentialValidationError, match="^Wellprod denied access to view 'q99_wells'"):
        await integration.read_view("q99_wells", data)


async def test_read_view_rejected_login_is_a_credential_error(install):
    install(lambda request: httpx.Response(401, text="secret leaked upstream"))
    integration, data = _reader(SourceEnum.datawell)

    with pytest.raises(CredentialValidationError, match="^Datawell rejected"):
        await integration.read_view("q99_pozo", data)


@pytest.mark.parametrize("page", [
    httpx.Response(200, json={"rows": []}),
    httpx.Response(200, json=[1, 2]),
    httpx.Response(200, text="not json"),
    httpx.Response(500, text="secret leaked upstream"),
])
async def test_read_view_bad_page_is_a_sanitized_integration_error(install, page):
    install(lambda request: httpx.Response(200, json={"token": "jwt"}) if request.method == "POST" else page)
    integration, data = _reader()

    with pytest.raises(IntegrationError) as error:
        await integration.read_view("q99_wells", data)
    assert not isinstance(error.value, CredentialValidationError)
    assert "secret" not in str(error.value)
    assert str(error.value).startswith("Wellprod ")


async def test_read_view_stops_at_the_page_cap(install, monkeypatch):
    monkeypatch.setattr("q99_utils.integrations.sources.dccsoft_connection.MAX_PAGES", 3)
    gets = []

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"token": "jwt"})
        gets.append(request)
        return httpx.Response(200, json=[{"pozo": "A"}])

    install(handler)
    integration, data = _reader()

    with pytest.raises(IntegrationError, match="did not end within 3 pages"):
        await integration.read_view("q99_wells", data, page_size=1)
    assert len(gets) == 3
