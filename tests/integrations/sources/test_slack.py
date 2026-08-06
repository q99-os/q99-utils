"""SlackIntegration.api_status.

Covers the failure modes the old implementation got wrong: it caught an
exception httpx never raises, and trusted the status code even though Slack
reports auth failures with 200 + ``ok: false``.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.sources.slack import SLACK_AUTH_TEST_URL, SlackIntegration
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData


def _response(status_code: int, *, json=None, text=None) -> httpx.Response:
    request = httpx.Request("POST", SLACK_AUTH_TEST_URL)
    if text is not None:
        return httpx.Response(status_code, text=text, request=request)
    return httpx.Response(status_code, json=json, request=request)


def _patch_transport(monkeypatch, *, response=None, exc=None) -> None:
    """Swap httpx.AsyncClient for one that replays a canned response/error."""

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            if exc is not None:
                raise exc
            return response

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)


@pytest.fixture
def integration() -> SlackIntegration:
    return SlackIntegration(source=SourceEnum.slack, um_sdk=None)


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(source=SourceEnum.slack, api_key="xoxb-token")


async def test_valid_token_is_accepted(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, response=_response(200, json={"ok": True, "team": "q99"}))
    assert await integration.api_status(credentials) is True


async def test_invalid_token_reported_as_200_with_ok_false(monkeypatch, integration, credentials):
    # Slack's actual behaviour for a bad token — the status code is 200, so
    # only the body reveals the failure.
    _patch_transport(monkeypatch, response=_response(200, json={"ok": False, "error": "invalid_auth"}))
    assert await integration.api_status(credentials) is False


async def test_http_error_status_is_reported_as_false(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, response=_response(401, json={"ok": False}))
    assert await integration.api_status(credentials) is False


async def test_network_failure_is_reported_as_false(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, exc=httpx.ConnectError("dns down"))
    assert await integration.api_status(credentials) is False


async def test_timeout_is_reported_as_false(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, exc=httpx.ReadTimeout("slow"))
    assert await integration.api_status(credentials) is False


async def test_non_json_body_is_reported_as_false(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, response=_response(200, text="<html>maintenance</html>"))
    assert await integration.api_status(credentials) is False
