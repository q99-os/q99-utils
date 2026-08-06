"""AzureADIntegration.test_connection.

It used to raise ``fastapi.HTTPException`` directly, tying the library to a web
framework. Now it raises ``CredentialValidationError`` and the host maps it.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.exceptions import CredentialValidationError
from q99_utils.integrations.registry import get_integration_class
from q99_utils.integrations.sources.azure_ad import (
    GRAPH_GROUPS_URL,
    AzureADIntegration,
)
from q99_utils.models import OnboardingData, SourceEnum

TOKEN_URL_FRAGMENT = "login.microsoftonline.com"


def _patch_transport(monkeypatch, *, token_result, groups_result=None) -> None:
    """Swap httpx.AsyncClient for one replaying canned token/groups outcomes.

    Each ``*_result`` is either an ``httpx.Response`` to return or an exception
    to raise.
    """

    def _deliver(result):
        if isinstance(result, BaseException):
            raise result
        return result

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            assert TOKEN_URL_FRAGMENT in url
            return _deliver(token_result)

        async def get(self, url, **kwargs):
            assert url == GRAPH_GROUPS_URL
            return _deliver(groups_result)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)


def _response(status_code: int, *, url: str, json=None) -> httpx.Response:
    return httpx.Response(status_code, json=json, request=httpx.Request("POST", url))


@pytest.fixture
def integration() -> AzureADIntegration:
    return AzureADIntegration(source=SourceEnum.azure_ad, um_sdk=None)


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.azure_ad,
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
    )


async def test_valid_credentials_pass_silently(monkeypatch, integration, credentials):
    _patch_transport(
        monkeypatch,
        token_result=_response(200, url=TOKEN_URL_FRAGMENT, json={"access_token": "tok"}),
        groups_result=_response(200, url=GRAPH_GROUPS_URL, json={"value": []}),
    )
    assert await integration.test_connection(credentials) is None


async def test_bad_secret_raises_credential_validation_error(monkeypatch, integration, credentials):
    _patch_transport(
        monkeypatch,
        token_result=_response(401, url=TOKEN_URL_FRAGMENT, json={"error": "invalid_client"}),
    )

    with pytest.raises(CredentialValidationError) as exc_info:
        await integration.test_connection(credentials)

    assert "could not acquire access token" in exc_info.value.message
    assert exc_info.value.source == "azure_ad"


async def test_missing_graph_permission_raises_credential_validation_error(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        token_result=_response(200, url=TOKEN_URL_FRAGMENT, json={"access_token": "tok"}),
        groups_result=_response(403, url=GRAPH_GROUPS_URL, json={"error": "Forbidden"}),
    )

    with pytest.raises(CredentialValidationError) as exc_info:
        await integration.test_connection(credentials)

    assert "Group.Read.All" in exc_info.value.message


async def test_network_failure_is_a_credential_error_not_a_raw_httpx_error(
    monkeypatch, integration, credentials
):
    # Previously only HTTPStatusError was caught, so a timeout escaped as a
    # raw httpx error and surfaced to the caller as a 500.
    _patch_transport(monkeypatch, token_result=httpx.ConnectTimeout("unreachable"))

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


async def test_error_is_framework_agnostic(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, token_result=httpx.ConnectError("down"))

    with pytest.raises(CredentialValidationError) as exc_info:
        await integration.test_connection(credentials)

    # The library must not leak a transport/framework type to its callers.
    assert not any(
        base.__module__.startswith("fastapi") or base.__module__.startswith("starlette")
        for base in type(exc_info.value).__mro__
    )


def test_serves_both_azure_ad_and_microsoft_sso():
    # One app registration backs group sync and SSO login, so both sources map
    # here — but they stay separate sources so their credentials never collide.
    assert get_integration_class(SourceEnum.azure_ad) is AzureADIntegration
    assert get_integration_class(SourceEnum.microsoft_sso) is AzureADIntegration
