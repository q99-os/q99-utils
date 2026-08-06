"""AlamoIntegration — envelope construction, URL resolution, response validation.

Alamo authenticates with an ``apiKey`` inside the POST body rather than a header,
and all eight endpoints share one request envelope, so nearly all the behaviour
worth testing is "what went on the wire".
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from q99_utils.integrations.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.registry import get_integration_class
from q99_utils.integrations.sources.alamo import ENDPOINT_LIMITS, AlamoIntegration
from q99_utils.models import OnboardingData, SourceEnum
from tests.integrations.fakes import FakeUserManagerSDK, HttpRecorder


@pytest.fixture
def integration() -> AlamoIntegration:
    return AlamoIntegration(source=SourceEnum.alamo, um_sdk=None)


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.alamo, api_key="secret-key", tenant_name="acme"
    )


# Registration


def test_alamo_is_registered_for_its_source():
    assert get_integration_class(SourceEnum.alamo) is AlamoIntegration


# Request envelope


async def test_envelope_carries_version_key_tipo_and_parametros(
    monkeypatch, integration, credentials
):
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.read_comments(
        "2026-01-01 06:00:00",
        "2026-06-10 06:00:00",
        pozos=["POZO-001"],
        data=credentials,
    )

    assert recorder.last["json"] == {
        "version": 1,
        "apiKey": "secret-key",
        "tipo": "readComments",
        "parametros": {
            "pozos": ["POZO-001"],
            "fecha_inicial": "2026-01-01 06:00:00",
            "fecha_final": "2026-06-10 06:00:00",
        },
    }


async def test_omitted_entities_are_sent_as_null_to_mean_all(
    monkeypatch, integration, credentials
):
    # The API treats NULL as "every well" — the key must be present, not dropped.
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.read_comments(
        "2026-01-01 06:00:00", "2026-06-10 06:00:00", data=credentials
    )

    assert recorder.last["json"]["parametros"]["pozos"] is None


async def test_masicos_endpoint_uses_the_masicos_parameter(
    monkeypatch, integration, credentials
):
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.read_comments_masicos(
        "2026-01-01 06:00:00", "2026-06-10 06:00:00", masicos=["G 002"], data=credentials
    )

    parametros = recorder.last["json"]["parametros"]
    assert parametros["masicos"] == ["G 002"]
    assert "pozos" not in parametros


async def test_datetime_arguments_are_formatted_for_the_api(
    monkeypatch, integration, credentials
):
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.ensayo_pozo(
        datetime(2026, 1, 1, 6, 0, 0), datetime(2026, 6, 10, 6, 0, 0), data=credentials
    )

    parametros = recorder.last["json"]["parametros"]
    assert parametros["fecha_inicial"] == "2026-01-01 06:00:00"
    assert parametros["fecha_final"] == "2026-06-10 06:00:00"


# Base URL resolution


async def test_url_is_built_from_the_tenant_name(monkeypatch, integration, credentials):
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.presiones_fondo(
        "2026-01-01 00:00:00", "2026-01-02 00:00:00", data=credentials
    )

    assert (
        recorder.last["url"]
        == "https://acme-api.alamo-analytics.com/externalApi/presionesFondo"
    )


async def test_api_base_overrides_the_tenant_template(monkeypatch, integration):
    creds = OnboardingData(
        source=SourceEnum.alamo,
        api_key="secret-key",
        tenant_name="acme",
        api_base="https://alamo.internal/externalApi/",
    )
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.diagnosticos(
        "2026-01-01 00:00:00", "2026-01-02 00:00:00", data=creds
    )

    assert recorder.last["url"] == "https://alamo.internal/externalApi/diagnosticos"


async def test_credential_without_tenant_or_api_base_is_rejected(
    monkeypatch, integration
):
    creds = OnboardingData(source=SourceEnum.alamo, api_key="secret-key")
    HttpRecorder(json={"data": []}).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.diagnosticos(
            "2026-01-01 00:00:00", "2026-01-02 00:00:00", data=creds
        )


async def test_credentials_are_loaded_from_user_manager_when_not_supplied(monkeypatch):
    um_sdk = FakeUserManagerSDK(
        credential={
            "source": str(SourceEnum.alamo),
            "api_key": "key-from-um",
            "tenant_name": "umtenant",
        }
    )
    integration = AlamoIntegration(source=SourceEnum.alamo, um_sdk=um_sdk)
    integration.credential_id = "cred-1"
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.produccion_solidos("2026-01-01 00:00:00", "2026-01-02 00:00:00")

    assert recorder.last["json"]["apiKey"] == "key-from-um"
    assert recorder.last["url"].startswith("https://umtenant-api.alamo-analytics.com/")


# Responses


async def test_the_data_array_is_returned(monkeypatch, integration, credentials):
    rows = [
        {
            "fecha": "2026-01-02 10:00:00",
            "pozo": "POZO-001",
            "presion_fondo": 1234.5,
            "presion_fondo_inicial": None,
        }
    ]
    HttpRecorder(json={"data": rows}).install(monkeypatch)

    result = await integration.presiones_fondo(
        "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
    )

    assert result == rows


async def test_response_without_a_data_key_is_rejected(
    monkeypatch, integration, credentials
):
    HttpRecorder(json={"error": "something went wrong"}).install(monkeypatch)

    with pytest.raises(IntegrationError):
        await integration.read_comments(
            "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
        )


async def test_response_whose_data_is_not_a_list_is_rejected(
    monkeypatch, integration, credentials
):
    HttpRecorder(json={"data": {"fecha": "2026-01-01 00:00:00"}}).install(monkeypatch)

    with pytest.raises(IntegrationError):
        await integration.read_comments(
            "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
        )


async def test_non_json_body_is_rejected(monkeypatch, integration, credentials):
    HttpRecorder(text="<html>maintenance</html>").install(monkeypatch)

    with pytest.raises(IntegrationError):
        await integration.read_comments(
            "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
        )


async def test_http_error_status_propagates_to_the_caller(
    monkeypatch, integration, credentials
):
    # Retry/backoff is the host's decision, so transport errors are not swallowed.
    HttpRecorder(json={"data": []}, status_code=500).install(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        await integration.read_comments(
            "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
        )


# Truncation — we do not paginate, so hitting the cap must at least be visible.


async def test_response_at_the_endpoint_limit_warns_about_truncation(
    monkeypatch, integration, credentials, caplog
):
    rows = [{"fecha": "2026-01-01 00:00:00"}] * ENDPOINT_LIMITS["readComments"]
    HttpRecorder(json={"data": rows}).install(monkeypatch)

    with caplog.at_level("WARNING", logger="q99_utils"):
        await integration.read_comments(
            "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
        )

    assert "readComments" in caplog.text


async def test_response_below_the_endpoint_limit_does_not_warn(
    monkeypatch, integration, credentials, caplog
):
    HttpRecorder(json={"data": [{"fecha": "2026-01-01 00:00:00"}]}).install(monkeypatch)

    with caplog.at_level("WARNING", logger="q99_utils"):
        await integration.read_comments(
            "2026-01-01 00:00:00", "2026-02-01 00:00:00", data=credentials
        )

    assert caplog.text == ""


# actionHub takes entity_type/entity_names instead of pozos


async def test_action_hub_sends_entity_type_and_entity_names(
    monkeypatch, integration, credentials
):
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.action_hub(
        "2026-01-01 06:00:00",
        "2026-06-10 06:00:00",
        entity_type="Pozo",
        entity_names=["POZO-001"],
        data=credentials,
    )

    assert recorder.last["json"]["parametros"] == {
        "fecha_inicial": "2026-01-01 06:00:00",
        "fecha_final": "2026-06-10 06:00:00",
        "entity_type": "Pozo",
        "entity_names": ["POZO-001"],
    }


async def test_action_hub_rejects_entity_names_without_an_entity_type(
    integration, credentials
):
    # The API requires entity_type whenever entity_names is set; catching it here
    # saves a round-trip. No transport is patched — this must fail before any call.
    with pytest.raises(ValueError):
        await integration.action_hub(
            "2026-01-01 06:00:00",
            "2026-06-10 06:00:00",
            entity_names=["POZO-001"],
            data=credentials,
        )


# Credential validation


async def test_test_connection_accepts_a_working_credential(
    monkeypatch, integration, credentials
):
    recorder = HttpRecorder(json={"data": []}).install(monkeypatch)

    await integration.test_connection(credentials)

    # Validated with a real endpoint over a deliberately tiny window.
    assert recorder.last["json"]["tipo"] == "readComments"


async def test_test_connection_rejects_a_bad_api_key(
    monkeypatch, integration, credentials
):
    HttpRecorder(json={"data": []}, status_code=401).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


async def test_test_connection_reports_a_network_failure(
    monkeypatch, integration, credentials
):
    HttpRecorder(exc=httpx.ConnectError("dns down")).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


async def test_test_connection_rejects_a_malformed_response(
    monkeypatch, integration, credentials
):
    # A 200 that isn't the documented envelope means we aren't talking to Alamo.
    HttpRecorder(json={"unexpected": True}).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)
