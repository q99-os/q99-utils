"""Telling a dead grant apart from a dead app.

The two look alike — the provider refuses to hand over a token — but they need
opposite answers. A dead grant is the owner's to reconnect; a dead app secret takes
every integration running against it down at once and only an administrator can
replace it. Sending the owner around a reconnect loop that cannot succeed is the
failure this guards against.
"""

import httpx
import pytest

from q99_utils.integrations.core import AppCredentialExpired, CredentialExpired
from q99_utils.integrations.core.google_oauth import translate_refresh_error
from q99_utils.integrations.core.microsoft_graph import (
    refresh_delegated_token,
    request_graph_token,
)


def _answer(monkeypatch, payload: dict, status_code: int = 401):
    """Make every token request answer with this body."""
    async def post(self, url, **kwargs):
        return httpx.Response(
            status_code=status_code, json=payload, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)


# ── Microsoft, app-only (client_credentials) ─────────────────────────


@pytest.mark.asyncio
async def test_app_only_rejected_client_blames_the_app(monkeypatch):
    _answer(monkeypatch, {"error": "invalid_client", "error_description": "AADSTS7000222"})

    with pytest.raises(AppCredentialExpired) as raised:
        await request_graph_token(tenant_id="t", client_id="c", client_secret="dead")

    assert "administrator" in str(raised.value)


@pytest.mark.asyncio
async def test_app_only_other_errors_stay_transient(monkeypatch):
    """Anything else is a bad minute, not a dead app: it must keep being retryable."""
    _answer(monkeypatch, {"error": "temporarily_unavailable"}, status_code=503)

    with pytest.raises(httpx.HTTPStatusError):
        await request_graph_token(tenant_id="t", client_id="c", client_secret="s")


# ── Microsoft, delegated (refresh_token) ─────────────────────────────


@pytest.mark.asyncio
async def test_delegated_rejected_client_blames_the_app(monkeypatch):
    _answer(monkeypatch, {"error": "invalid_client"})

    with pytest.raises(AppCredentialExpired):
        await refresh_delegated_token(
            tenant_id="t", client_id="c", client_secret="dead", refresh_token="r",
        )


@pytest.mark.asyncio
async def test_delegated_rejected_grant_still_blames_the_owner(monkeypatch):
    """The case that already worked has to keep working, and stay a different error."""
    _answer(monkeypatch, {"error": "invalid_grant"})

    with pytest.raises(CredentialExpired) as raised:
        await refresh_delegated_token(
            tenant_id="t", client_id="c", client_secret="s", refresh_token="revoked",
        )

    assert not isinstance(raised.value, AppCredentialExpired)
    assert "Reconnect" in str(raised.value)


# ── Google ───────────────────────────────────────────────────────────


def test_google_rejected_client_blames_the_app():
    with pytest.raises(AppCredentialExpired):
        translate_refresh_error(Exception({"error": "invalid_client"}), source="googledrive")


def test_google_rejected_grant_still_blames_the_owner():
    with pytest.raises(CredentialExpired) as raised:
        translate_refresh_error(Exception({"error": "invalid_grant"}), source="googledrive")

    assert not isinstance(raised.value, AppCredentialExpired)


def test_google_leaves_anything_else_untouched():
    original = Exception("connection reset")

    with pytest.raises(Exception) as raised:
        translate_refresh_error(original, source="gmail")

    assert raised.value is original


# ── Which app each source runs against ───────────────────────────────


def test_every_delegated_and_app_only_source_knows_its_app():
    from q99_utils.integrations.core import app_source_for

    assert str(app_source_for("googledrive")) == "google_oauth_app"
    assert str(app_source_for("gmail")) == "google_oauth_app"
    assert str(app_source_for("outlook")) == "microsoft_oauth_app"
    assert str(app_source_for("sharepoint")) == "microsoft_oauth_app"
    assert str(app_source_for("azure_ad")) == "microsoft_oauth_app"


def test_a_source_that_brings_its_own_credentials_has_no_app():
    from q99_utils.integrations.core import app_source_for

    assert app_source_for("slack") is None
    assert app_source_for("not_a_source") is None
