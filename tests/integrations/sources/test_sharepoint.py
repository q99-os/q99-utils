"""Fetching a SharePoint file by its human-readable path.

`get_files_from_path` addresses a drive *item id*; this covers the path-addressed sibling
(`/drive/root:/{path}:/content`), which is what a report definition can name readably — and which
survives the delete-and-re-upload that a hand-maintained workbook actually gets.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.sources.sharepoint import SharepointIntegration

SITE_ID = "contoso.sharepoint.com,site-guid,web-guid"


def _patch_transport(monkeypatch, *, response: httpx.Response) -> list:
    """Answer the token POST automatically and serve `response` for the Graph GET.

    Returns the list of requested URLs so a test can assert how the file was addressed.
    """
    requested: list = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, *args, **kwargs):
            requested.append(url)
            return httpx.Response(
                200,
                json={"access_token": "tok", "expires_in": 3600},
                request=httpx.Request("POST", url),
            )

        async def get(self, url, *args, **kwargs):
            requested.append(url)
            return httpx.Response(
                response.status_code,
                content=response.content,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return requested


def _integration(monkeypatch) -> SharepointIntegration:
    integration = SharepointIntegration.__new__(SharepointIntegration)

    async def credentials(*args, **kwargs):
        return {"site_id": SITE_ID}

    async def token(*args, **kwargs):
        return "tok"

    monkeypatch.setattr(integration, "get_credentials", credentials, raising=False)
    monkeypatch.setattr(integration, "get_access_token", token, raising=False)
    integration.credentials = {"site_id": SITE_ID}
    return integration


async def test_addresses_the_file_by_path_not_by_item_id(monkeypatch):
    requested = _patch_transport(
        monkeypatch, response=httpx.Response(200, content=b"PK\x03\x04xlsx-bytes")
    )
    integration = _integration(monkeypatch)

    result = await integration.get_file_by_path("Test_folder/Base de datos.xlsx")

    assert result is not None
    assert result.read() == b"PK\x03\x04xlsx-bytes"
    graph_get = next(u for u in requested if "graph.microsoft.com" in u)
    # path-addressed, under the site's default drive — NOT /drive/items/{id}/content
    assert f"/sites/{SITE_ID}/drive/root:/Test_folder/Base de datos.xlsx:/content" in graph_get
    assert "/drive/items/" not in graph_get


async def test_a_leading_slash_is_tolerated(monkeypatch):
    """A path copied out of a browser often keeps its leading slash; that must not 404."""
    requested = _patch_transport(monkeypatch, response=httpx.Response(200, content=b"x"))
    integration = _integration(monkeypatch)

    await integration.get_file_by_path("/Test_folder/Base de datos.xlsx")

    graph_get = next(u for u in requested if "graph.microsoft.com" in u)
    assert "root:/Test_folder/Base de datos.xlsx:/content" in graph_get
    assert "root://" not in graph_get


async def test_a_missing_file_returns_none_rather_than_raising(monkeypatch):
    """The caller degrades one report section; it must not take the whole generation down."""
    _patch_transport(monkeypatch, response=httpx.Response(404, content=b'{"error":{}}'))
    integration = _integration(monkeypatch)

    assert await integration.get_file_by_path("Nope/missing.xlsx") is None
