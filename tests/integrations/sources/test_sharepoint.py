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


# A full URL addresses a file in ANY library, which is the only way to reach one that is not the
# site's default — `/drive` means the default library and nothing can redirect it.

VISTA_URL = (
    "https://vistaoilandgas.sharepoint.com/sites/BI_VacaMuerta"
    "/Reservorenado/Gas Lift/Base de datos.xlsx"
)
VISTA_TOKEN = (
    "u!aHR0cHM6Ly92aXN0YW9pbGFuZGdhcy5zaGFyZXBvaW50LmNvbS9zaXRlcy9CSV9WYWNhTXVlcnRhL1Jlc2Vydm9y"
    "ZW5hZG8vR2FzJTIwTGlmdC9CYXNlJTIwZGUlMjBkYXRvcy54bHN4"
)


async def test_a_full_url_is_resolved_through_shares(monkeypatch):
    requested = _patch_transport(
        monkeypatch, response=httpx.Response(200, content=b"PK\x03\x04xlsx-bytes")
    )
    integration = _integration(monkeypatch)

    result = await integration.get_file_by_path(VISTA_URL)

    assert result is not None
    assert result.read() == b"PK\x03\x04xlsx-bytes"
    graph_get = next(u for u in requested if "graph.microsoft.com" in u)
    assert f"/shares/{VISTA_TOKEN}/driveItem/content" in graph_get
    # the site in the URL decides, so the credential's site_id must not appear
    assert f"/sites/{SITE_ID}" not in graph_get
    assert "/drive/root:/" not in graph_get


async def test_spaces_and_percent_encoding_address_the_same_file(monkeypatch):
    """The token is the base64 of the URL, so the two spellings of a space would otherwise be two
    different files — and which one a caller has depends on how they copied the link."""
    requested_raw = _patch_transport(monkeypatch, response=httpx.Response(200, content=b"x"))
    await _integration(monkeypatch).get_file_by_path(VISTA_URL)

    requested_encoded = _patch_transport(monkeypatch, response=httpx.Response(200, content=b"x"))
    await _integration(monkeypatch).get_file_by_path(VISTA_URL.replace(" ", "%20"))

    raw = next(u for u in requested_raw if "graph.microsoft.com" in u)
    encoded = next(u for u in requested_encoded if "graph.microsoft.com" in u)
    assert raw == encoded
    assert VISTA_TOKEN in raw


async def test_an_unreachable_url_returns_none_rather_than_raising(monkeypatch):
    """A URL for a site the app has no grant for answers 403; it degrades like a missing file."""
    _patch_transport(monkeypatch, response=httpx.Response(403, content=b'{"error":{}}'))
    integration = _integration(monkeypatch)

    assert await integration.get_file_by_path(VISTA_URL) is None


async def test_a_server_relative_path_gets_the_tenant_host_from_the_credential(monkeypatch):
    """A definition should not have to repeat the tenant hostname the credential already knows."""
    requested = _patch_transport(monkeypatch, response=httpx.Response(200, content=b"x"))
    integration = _integration(monkeypatch)
    # deliberately not the host inside SITE_ID, so preferring tenant_name is what makes this pass
    integration.credentials = {"site_id": SITE_ID, "tenant_name": "vistaoilandgas"}

    await integration.get_file_by_path("/sites/BI/Lib/Gas Lift/Base de datos.xlsx")

    graph_get = next(u for u in requested if "graph.microsoft.com" in u)
    expected = SharepointIntegration._share_token(
        "https://vistaoilandgas.sharepoint.com/sites/BI/Lib/Gas Lift/Base de datos.xlsx"
    )
    assert f"/shares/{expected}/driveItem/content" in graph_get


async def test_the_host_falls_back_to_the_site_id(monkeypatch):
    """site_id is 'hostname,site-guid,web-guid', so it carries the host when tenant_name is unset."""
    requested = _patch_transport(monkeypatch, response=httpx.Response(200, content=b"x"))
    integration = _integration(monkeypatch)
    integration.credentials = {"site_id": SITE_ID}

    await integration.get_file_by_path("/sites/BI/Lib/x.xlsx")

    graph_get = next(u for u in requested if "graph.microsoft.com" in u)
    expected = SharepointIntegration._share_token(
        "https://contoso.sharepoint.com/sites/BI/Lib/x.xlsx"
    )
    assert f"/shares/{expected}/driveItem/content" in graph_get
