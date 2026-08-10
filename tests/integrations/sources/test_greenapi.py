"""GreenAPI host resolution and instance status.

Two bugs motivated these. The MCP server resolved its own host and drifted to a
different sandbox server than the engine's, and the production constant pointed
at ``green-api.com`` — the marketing site, which answers 404 HTML to every API
path. Both were invisible because nothing asserted on the URLs.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.core import IntegrationConfig, IntegrationContext
from q99_utils.integrations.sources.greenapi import (
    PROD_API_URL,
    SANDBOX_API_URL,
    GreenAPIIntegration,
    resolve_api_url,
)
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData


def _integration(environment: str) -> GreenAPIIntegration:
    context = IntegrationContext(config=IntegrationConfig(environment=environment))
    return GreenAPIIntegration(source=SourceEnum.greenapi, um_sdk=None, context=context)


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.greenapi, instance_id="710722706236", api_key="token"
    )


# Host resolution


def test_only_production_talks_to_the_production_host():
    assert resolve_api_url("prod") == PROD_API_URL


@pytest.mark.parametrize("environment", ["local", "dev", "test", "stage", "sandbox"])
def test_everything_else_talks_to_the_sandbox(environment):
    """stage and sandbox included — the MCP server used to send those to production."""
    assert resolve_api_url(environment) == SANDBOX_API_URL


@pytest.mark.parametrize("url", [PROD_API_URL, SANDBOX_API_URL])
def test_both_hosts_are_api_hosts(url):
    """``green-api.com`` without the api prefix is the website, not the API."""
    host = url.removeprefix("https://")
    assert url.startswith("https://")
    assert host.startswith("api.") or ".api." in host


def test_the_integration_resolves_the_host_from_its_config():
    assert _integration("prod").api_url == PROD_API_URL
    assert _integration("dev").api_url == SANDBOX_API_URL


# Instance status


def _patch_transport(monkeypatch, *, status_code, payload) -> list:
    requested: list = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, **kwargs):
            requested.append(url)
            return httpx.Response(
                status_code, json=payload, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return requested


async def test_authorized_instance_passes(monkeypatch, credentials):
    requested = _patch_transport(
        monkeypatch, status_code=200, payload={"stateInstance": "authorized"}
    )

    assert await _integration("dev").api_status(credentials) is True
    assert requested[0].startswith(SANDBOX_API_URL)
    assert "/waInstance710722706236/getStateInstance/token" in requested[0]


async def test_unauthorized_instance_fails(monkeypatch, credentials):
    """A fresh instance is notAuthorized until someone scans the QR."""
    _patch_transport(
        monkeypatch, status_code=200, payload={"stateInstance": "notAuthorized"}
    )

    assert await _integration("dev").api_status(credentials) is False
