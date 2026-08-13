"""Directory reads and subscriptions on AzureADIntegration.

These moved out of the user manager, where they were tested against a mocked
``requests``. The shaping is what matters: pagination followed to the end, only
groups kept from the heterogeneous ``/memberOf`` collection, emails lowercased,
a missing resource distinguished from a transient failure.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.core.exceptions import IntegrationError, ResourceNotFound
from q99_utils.integrations.sources.azure_ad import AzureADIntegration
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

TOKEN_URL_FRAGMENT = "login.microsoftonline.com"


def _patch_transport(monkeypatch, *, pages) -> list:
    """Replay ``pages`` for successive Graph calls; record the URLs requested.

    Each entry is a status/json pair or an ``httpx.Response``. Token POSTs are
    answered automatically so tests only describe the Graph side.
    """
    requested: list = []
    remaining = list(pages)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            assert TOKEN_URL_FRAGMENT in url
            return httpx.Response(
                200, json={"access_token": "tok"}, request=httpx.Request("POST", url)
            )

        async def request(self, method, url, **kwargs):
            requested.append((method, url))
            status, payload = remaining.pop(0)
            return httpx.Response(
                status, json=payload, request=httpx.Request(method, url)
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return requested


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


# Groups


async def test_fetch_all_groups_returns_id_and_display_name(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        pages=[
            (200, {"value": [
                {"id": "g1", "displayName": "Engineers"},
                {"id": "g2", "displayName": "Admins"},
            ]}),
        ],
    )

    assert await integration.fetch_all_groups(credentials) == [
        {"id": "g1", "displayName": "Engineers"},
        {"id": "g2", "displayName": "Admins"},
    ]


async def test_fetch_all_groups_follows_pagination(monkeypatch, integration, credentials):
    requested = _patch_transport(
        monkeypatch,
        pages=[
            (200, {
                "value": [{"id": "g1", "displayName": "One"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups?page=2",
            }),
            (200, {"value": [{"id": "g2", "displayName": "Two"}]}),
        ],
    )

    groups = await integration.fetch_all_groups(credentials)

    assert [g["id"] for g in groups] == ["g1", "g2"]
    assert requested[1][1].endswith("page=2")


async def test_fetch_all_groups_skips_entries_missing_a_field(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        pages=[
            (200, {"value": [
                {"id": "g1", "displayName": "Kept"},
                {"id": "g2"},
                {"displayName": "No id"},
            ]}),
        ],
    )

    assert await integration.fetch_all_groups(credentials) == [
        {"id": "g1", "displayName": "Kept"}
    ]


async def test_fetch_group_by_id_returns_the_group(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, pages=[(200, {"id": "g9", "displayName": "QA"})])

    assert await integration.fetch_group_by_id("g9", credentials) == {
        "id": "g9",
        "displayName": "QA",
    }


async def test_missing_group_raises_resource_not_found(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, pages=[(404, {"error": "not found"})])

    with pytest.raises(ResourceNotFound):
        await integration.fetch_group_by_id("gone", credentials)


async def test_server_error_raises_integration_error(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, pages=[(500, {"error": "boom"})])

    with pytest.raises(IntegrationError) as exc_info:
        await integration.fetch_group_by_id("g1", credentials)

    assert not isinstance(exc_info.value, ResourceNotFound)


async def test_fetch_group_members_lowercases_and_falls_back_to_upn(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        pages=[
            (200, {"value": [
                {"mail": "Ana@Q99.AI"},
                {"userPrincipalName": "BOB@q99.ai"},
                {"displayName": "nested group, no address"},
            ]}),
        ],
    )

    assert await integration.fetch_group_members("g1", credentials) == [
        "ana@q99.ai",
        "bob@q99.ai",
    ]


# Users


async def test_fetch_all_user_emails_skips_users_without_mail(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        pages=[
            (200, {"value": [{"mail": "Ana@Q99.AI"}, {"mail": None}, {}]}),
        ],
    )

    assert await integration.fetch_all_user_emails(credentials) == ["ana@q99.ai"]


async def test_fetch_user_memberships_drops_directory_roles_and_units(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        pages=[
            (200, {"value": [
                {"@odata.type": "#microsoft.graph.group", "id": "g1", "displayName": "Eng"},
                {"@odata.type": "#microsoft.graph.directoryRole", "id": "r1", "displayName": "Admin"},
                {"@odata.type": "#microsoft.graph.administrativeUnit", "id": "a1", "displayName": "Unit"},
            ]}),
        ],
    )

    assert await integration.fetch_user_memberships("ana@q99.ai", credentials) == [
        {"id": "g1", "displayName": "Eng"},
    ]


async def test_fetch_user_group_names_returns_only_names(
    monkeypatch, integration, credentials
):
    _patch_transport(
        monkeypatch,
        pages=[
            (200, {"value": [
                {"@odata.type": "#microsoft.graph.group", "id": "g1", "displayName": "Eng"},
            ]}),
        ],
    )

    assert await integration.fetch_user_group_names("ana@q99.ai", credentials) == ["Eng"]


async def test_unknown_user_raises_resource_not_found(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, pages=[(404, {"error": "not found"})])

    with pytest.raises(ResourceNotFound):
        await integration.fetch_user_memberships("nobody@q99.ai", credentials)


# Change notifications


async def test_create_subscription_posts_the_payload(monkeypatch, integration, credentials):
    requested = _patch_transport(monkeypatch, pages=[(201, {"id": "sub1"})])

    result = await integration.create_subscription(
        resource="/groups",
        change_type="updated",
        notification_url="https://q99.ai/hook",
        client_state="secret",
        expiration="2026-01-01T00:00:00Z",
        data=credentials,
    )

    assert result == {"id": "sub1"}
    assert requested[0][0] == "POST"


async def test_delete_subscription_tolerates_an_empty_body(
    monkeypatch, integration, credentials
):
    requested = _patch_transport(monkeypatch, pages=[(204, None)])

    assert await integration.delete_subscription("sub1", credentials) is None
    assert requested[0][0] == "DELETE"


async def test_list_subscriptions_unwraps_value(monkeypatch, integration, credentials):
    _patch_transport(monkeypatch, pages=[(200, {"value": [{"id": "sub1"}]})])

    assert await integration.list_subscriptions(credentials) == [{"id": "sub1"}]
