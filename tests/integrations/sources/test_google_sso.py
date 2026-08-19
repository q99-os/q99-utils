"""GoogleSsoIntegration.test_connection — the invalid-code credential probe.

Google exposes no way to verify an OAuth web client without a user redirect, so
the probe sends a deliberately invalid authorization code. Google authenticates
the *client* before validating the *grant*, which separates the two failures:
``invalid_grant`` means the credentials are good, ``invalid_client`` means they
are not.

The important property is that anything the probe cannot interpret fails closed —
a probe that accidentally accepts bad credentials is worse than no probe.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.core.exceptions import CredentialValidationError
from q99_utils.integrations.core.registry import get_integration_class
from q99_utils.integrations.sources.google_sso import (
    GOOGLE_TOKEN_URL,
    GoogleSsoIntegration,
)
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData
from tests.integrations.fakes import FakeUserManagerSDK, HttpRecorder


@pytest.fixture
def integration() -> GoogleSsoIntegration:
    return GoogleSsoIntegration(
        source=SourceEnum.google_sso, um_sdk=None
    )


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.google_sso,
        client_id="123.apps.googleusercontent.com",
        client_secret="top-secret",
    )


def test_google_sso_is_registered_for_its_source():
    assert (
        get_integration_class(SourceEnum.google_sso)
        is GoogleSsoIntegration
    )


def test_the_same_probe_serves_the_company_oauth_app():
    assert (
        get_integration_class(SourceEnum.google_oauth_app)
        is GoogleSsoIntegration
    )


# The two documented outcomes


async def test_invalid_grant_means_the_credentials_are_good(
    monkeypatch, integration, credentials
):
    # Google reached the grant check, so it already accepted client_id/secret.
    HttpRecorder(json={"error": "invalid_grant"}, status_code=400).install(monkeypatch)

    await integration.test_connection(credentials)


async def test_invalid_client_is_rejected(monkeypatch, integration, credentials):
    HttpRecorder(json={"error": "invalid_client"}, status_code=401).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


# The probe request itself


async def test_probe_posts_the_client_credentials_to_googles_token_endpoint(
    monkeypatch, integration, credentials
):
    recorder = HttpRecorder(json={"error": "invalid_grant"}, status_code=400).install(
        monkeypatch
    )

    await integration.test_connection(credentials)

    assert recorder.last["url"] == GOOGLE_TOKEN_URL
    body = recorder.last["data"]
    assert body["grant_type"] == "authorization_code"
    assert body["client_id"] == "123.apps.googleusercontent.com"
    assert body["client_secret"] == "top-secret"
    assert body["code"]  # a throwaway code, but one must be sent


async def test_credentials_are_loaded_from_user_manager_when_not_supplied(monkeypatch):
    um_sdk = FakeUserManagerSDK(
        credential={
            "source": str(SourceEnum.google_sso),
            "client_id": "from-um",
            "client_secret": "secret-from-um",
        }
    )
    integration = GoogleSsoIntegration(
        source=SourceEnum.google_sso, um_sdk=um_sdk
    )
    integration.credential_id = "cred-1"
    recorder = HttpRecorder(json={"error": "invalid_grant"}, status_code=400).install(
        monkeypatch
    )

    await integration.test_connection()

    assert recorder.last["data"]["client_id"] == "from-um"


# Everything unrecognised must fail closed


async def test_an_unexpected_success_is_rejected(monkeypatch, integration, credentials):
    # A throwaway code should never mint a token. If it did, we don't understand
    # the response, so we must not report the credentials as valid.
    HttpRecorder(json={"access_token": "surprise"}, status_code=200).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


async def test_an_unknown_error_code_is_rejected(monkeypatch, integration, credentials):
    HttpRecorder(json={"error": "unsupported_grant_type"}, status_code=400).install(
        monkeypatch
    )

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


async def test_a_non_json_body_is_rejected(monkeypatch, integration, credentials):
    HttpRecorder(text="<html>502 Bad Gateway</html>", status_code=502).install(
        monkeypatch
    )

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


async def test_a_network_failure_is_rejected(monkeypatch, integration, credentials):
    HttpRecorder(exc=httpx.ConnectError("dns down")).install(monkeypatch)

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(credentials)


# Missing fields are caught before we bother Google


async def test_missing_client_secret_is_rejected_without_a_request(
    monkeypatch, integration
):
    creds = OnboardingData(
        source=SourceEnum.google_sso, client_id="123.apps.googleusercontent.com"
    )
    recorder = HttpRecorder(json={"error": "invalid_grant"}, status_code=400).install(
        monkeypatch
    )

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(creds)

    assert recorder.calls == []


async def test_missing_client_id_is_rejected_without_a_request(monkeypatch, integration):
    creds = OnboardingData(
        source=SourceEnum.google_sso, client_secret="top-secret"
    )
    recorder = HttpRecorder(json={"error": "invalid_grant"}, status_code=400).install(
        monkeypatch
    )

    with pytest.raises(CredentialValidationError):
        await integration.test_connection(creds)

    assert recorder.calls == []
