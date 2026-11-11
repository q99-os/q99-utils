"""Mirico's published bearer auth and authorized-site read contract."""

from datetime import datetime, timezone
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


@pytest.mark.parametrize("method,path,raw", [
    ("get_readings", "/readings", False),
    ("get_tse", "/tse", False),
    ("get_tse_daily_aggregate", "/tse-daily-aggregate", False),
    ("get_lq_clustering", "/lq-output/clustering", False),
    ("get_lq_kde", "/lq-output/kde", False),
    ("get_zone_emissions", "/total-zone-emissions", False),
    ("get_detections", "/detections", False),
    ("get_coverage", "/coverage", False),
    ("get_raw_air", "/raw-measurements/air/", True),
    ("get_raw_concentration", "/raw-measurements/concentration/", True),
    ("get_raw_wind", "/raw-measurements/wind/", True),
])
async def test_windowed_reads_use_provider_paths_and_parameters(
    install, integration, credentials, method, path, raw,
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[{"value": None}])

    install(handler)
    start = datetime(2026, 11, 8, 21, tzinfo=timezone.utc)
    end = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
    assert await getattr(integration, method)(33, start, end, credentials) == [{"value": None}]
    request = requests[0]
    assert request.url.path == f"/engine-api/deployments/33{path}"
    names = ("datetime_from", "datetime_to") if raw else ("start_time", "end_time")
    assert request.url.params[names[0]] == "2026-11-08T21:00:00"
    assert request.url.params[names[1]] == "2026-11-09T00:00:00"
    assert request.headers["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize("start,end,sent", [
    ("2026-11-08T18:00:00-03:00", "2026-11-08T19:00:00-03:00", ("2026-11-08T21:00:00", "2026-11-08T22:00:00")),
    ("2026-11-08T21:00:00Z", "2026-11-08T22:00:00Z", ("2026-11-08T21:00:00", "2026-11-08T22:00:00")),
    ("2026-11-08T21:00:00", "2026-11-08T22:00:00", ("2026-11-08T21:00:00", "2026-11-08T22:00:00")),
])
async def test_windows_reach_mirico_as_naive_utc(install, integration, credentials, start, end, sent):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    install(handler)
    await integration.get_raw_wind(33, start, end, credentials)
    await integration.get_tse_daily_aggregate(33, start, end, credentials)
    assert (requests[0].url.params["datetime_from"], requests[0].url.params["datetime_to"]) == sent
    assert (requests[1].url.params["start_time"], requests[1].url.params["end_time"]) == sent


@pytest.mark.parametrize("method,path,response", [
    ("get_deployment", "/deployments/33", {"id": 33}),
    ("get_site_limits", "/deployments/33/site-limits", {"type": "FeatureCollection", "features": []}),
    ("get_instrument_status", "/deployments/33/instrument-status/latest", None),
    ("get_targets", "/deployments/33/targets", [{"name": "R4"}]),
])
async def test_metadata_reads_accept_their_documented_shapes(
    install, integration, credentials, method, path, response,
):
    requests = []

    def handler(request):
        requests.append(request)
        if response is None:
            return httpx.Response(200, content=b"null", headers={"Content-Type": "application/json"})
        return httpx.Response(200, json=response)

    install(handler)
    assert await getattr(integration, method)(33, credentials) == response
    assert requests[0].url.path == f"/engine-api{path}"


async def test_rejects_invalid_scope_and_response_before_using_bad_data(install, integration, credentials):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"unexpected": "shape"})

    install(handler)
    with pytest.raises(ValueError, match="positive integer"):
        await integration.get_tse(0, "2026-11-08T00:00:00", "2026-11-09T00:00:00", credentials)
    with pytest.raises(ValueError, match="after start"):
        await integration.get_tse(33, "2026-11-09T00:00:00", "2026-11-08T00:00:00", credentials)
    with pytest.raises(ValueError, match="timezone"):
        await integration.get_tse(33, "2026-11-08T00:00:00Z", "2026-11-09T00:00:00", credentials)
    assert requests == []
    with pytest.raises(IntegrationError, match="invalid data list"):
        await integration.get_tse(33, "2026-11-08T00:00:00", "2026-11-09T00:00:00", credentials)
