"""Addressing and delivery for Microsoft Teams.

The client is the shared delegated one, so what is worth pinning here is what Teams
adds on top: the endpoints it calls, the shape of a message, and — above all — that
its refresh grant asks for the scopes Teams was consented with.
"""

from __future__ import annotations

import httpx
import pytest

from q99_utils.integrations.core import (
    DELEGATED_MAIL_SCOPES,
    DELEGATED_TEAMS_SCOPES,
    DelegatedGraphClient,
    ResourceNotFound,
)
from q99_utils.integrations.sources.teams import (
    CHATS,
    HISTORY_LIMIT,
    HTML_CONTENT,
    JOINED_TEAMS,
    SEARCH_LIMIT,
    SEARCH_QUERY,
    TeamsClient,
    message_body,
)
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

TOKEN_HOST = "login.microsoftonline.com"


@pytest.fixture
def credentials() -> OnboardingData:
    return OnboardingData(
        source=SourceEnum.teams,
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        api_key="stale-token",
        refresh_token="refresh-1",
    )


def _patch_transport(monkeypatch, *, responses) -> list:
    """Replay ``responses`` for successive calls; record (method, url, kwargs)."""
    calls: list = []
    remaining = list(responses)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def _answer(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            status, payload = remaining.pop(0)
            return httpx.Response(status, json=payload, request=httpx.Request(method, url))

        async def get(self, url, **kwargs):
            return await self._answer("GET", url, **kwargs)

        async def post(self, url, **kwargs):
            return await self._answer("POST", url, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return calls


def _token_calls(calls: list) -> list:
    return [call for call in calls if TOKEN_HOST in call[1]]


# The contract with the consent


def test_teams_refreshes_with_the_scopes_it_was_consented_with():
    """The set the refresh grant asks for has to be the set the person agreed to.

    Azure AD answers a refresh that reaches for an unconsented scope with
    invalid_grant, which is the same answer a revoked account gives — and hosts
    respond to that by turning the integration off. Inheriting the mail scopes here
    would disconnect Teams by itself, an hour after it was connected.
    """
    assert TeamsClient.refresh_scopes == DELEGATED_TEAMS_SCOPES
    assert TeamsClient.refresh_scopes != DELEGATED_MAIL_SCOPES


async def test_the_refresh_grant_carries_the_teams_scopes_on_the_wire(
    monkeypatch, credentials
):
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (401, {"error": "expired"}),
            (200, {"access_token": "fresh-token", "refresh_token": "refresh-2"}),
            (200, {"value": []}),
        ],
    )

    await TeamsClient(credentials).joined_teams()

    token_call = _token_calls(calls)[0]
    assert token_call[2]["data"]["scope"] == DELEGATED_TEAMS_SCOPES


def test_a_delegated_client_must_say_what_to_ask_for():
    """Forgetting the scopes is an error while the module loads, not while it runs."""
    with pytest.raises(TypeError):

        class Forgetful(DelegatedGraphClient):
            pass


def test_the_delegated_scopes_cover_every_call_the_client_makes():
    for scope in (
        "Team.ReadBasic.All",
        "Channel.ReadBasic.All",
        "ChannelMessage.Send",
        "ChannelMessage.Read.All",
        "Chat.Create",
        "ChatMessage.Send",
        "Chat.Read",
        "User.ReadBasic.All",
        "offline_access",
    ):
        assert scope in DELEGATED_TEAMS_SCOPES


def test_reading_a_chat_asks_for_reading_and_nothing_more():
    """``Chat.Read`` covers the history. ``Chat.ReadWrite`` would also hand over every
    chat the person is in for writing, which nothing here does."""
    assert "Chat.Read" in DELEGATED_TEAMS_SCOPES
    assert "Chat.ReadWrite" not in DELEGATED_TEAMS_SCOPES


def test_turning_teams_on_needs_an_administrator_of_the_tenant():
    """The property this pins is not a permission, it is who can turn Teams on.

    ``ChannelMessage.Read.All`` is the one Teams scope Graph marks admin-consent-
    required, and reading channel history is not possible without it. The trade was
    made on purpose: every connection — including the ones that only want to send a
    message — waits until an administrator grants it for the whole tenant, and that
    grant belongs with the registration of the company's Microsoft app, which an
    administrator already does.

    Dropping it back out of the set is a product decision, not a cleanup: it takes
    channel history and the search over it away with it.
    """
    assert "ChannelMessage.Read.All" in DELEGATED_TEAMS_SCOPES


# Payloads


def test_the_body_uses_the_lowercase_content_type_teams_expects():
    assert message_body("hello") == {"body": {"contentType": HTML_CONTENT, "content": "hello"}}


# Reads


async def test_joined_teams_are_listed_with_their_ids(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[(200, {"value": [{"id": "t1", "displayName": "Drilling"}]})],
    )

    teams = await TeamsClient(credentials).joined_teams()

    assert teams == [{"id": "t1", "name": "Drilling"}]
    assert calls[0][1].endswith(JOINED_TEAMS)


async def test_an_entry_without_a_name_is_dropped(monkeypatch, credentials):
    """It could not be offered to a person, so returning it only invites a guess."""
    _patch_transport(
        monkeypatch,
        responses=[(200, {"value": [{"id": "t1"}, {"id": "t2", "displayName": "Ok"}]})],
    )

    assert await TeamsClient(credentials).joined_teams() == [{"id": "t2", "name": "Ok"}]


async def test_channels_are_asked_for_the_team_given(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[(200, {"value": [{"id": "c1", "displayName": "General"}]})],
    )

    channels = await TeamsClient(credentials).channels("t1")

    assert channels == [{"id": "c1", "name": "General"}]
    assert "/teams/t1/channels" in calls[0][1]


async def test_a_missing_team_is_a_resource_not_found(monkeypatch, credentials):
    _patch_transport(monkeypatch, responses=[(404, {"error": "not found"})])

    with pytest.raises(ResourceNotFound):
        await TeamsClient(credentials).channels("nope")


# Finding someone


async def test_finding_someone_searches_instead_of_prefix_matching(monkeypatch, credentials):
    """A surname has to find a person the same way a first name does."""
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (200, {"value": [{"id": "u1", "displayName": "Ana Diaz", "mail": "ana@q99.ai"}]})
        ],
    )

    people = await TeamsClient(credentials).find_people("Diaz")

    assert people == [{"name": "Ana Diaz", "address": "ana@q99.ai"}]
    params = calls[0][2]["params"]
    assert params["$search"] == '"displayName:Diaz" OR "mail:Diaz"'
    assert params["$top"] == str(SEARCH_LIMIT)
    assert calls[0][2]["headers"]["ConsistencyLevel"] == "eventual"


async def test_someone_without_a_mailbox_falls_back_to_their_principal_name(
    monkeypatch, credentials
):
    _patch_transport(
        monkeypatch,
        responses=[
            (
                200,
                {"value": [{"id": "u1", "displayName": "No Mailbox", "userPrincipalName": "sb@q99.ai"}]},
            )
        ],
    )

    assert await TeamsClient(credentials).find_people("Sin") == [
        {"name": "No Mailbox", "address": "sb@q99.ai"}
    ]


async def test_an_empty_query_asks_graph_nothing(monkeypatch, credentials):
    calls = _patch_transport(monkeypatch, responses=[])

    assert await TeamsClient(credentials).find_people("   ") == []
    assert calls == []


# Writes


async def test_a_channel_message_goes_to_that_channel_with_the_text(monkeypatch, credentials):
    calls = _patch_transport(monkeypatch, responses=[(201, {"id": "m1"})])

    result = await TeamsClient(credentials).send_channel_message(
        team_id="t1", channel_id="c1", text="testing"
    )

    assert result == {"id": "m1"}
    method, url, kwargs = calls[0]
    assert method == "POST"
    assert url.endswith("/teams/t1/channels/c1/messages")
    assert kwargs["json"] == message_body("testing")


async def test_a_direct_message_names_both_sides_of_the_chat(monkeypatch, credentials):
    """Graph refuses a one-on-one chat that names only the other person."""
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (200, {"id": "them"}),
            (200, {"id": "me"}),
            (201, {"id": "chat-1"}),
            (201, {"id": "m1"}),
        ],
    )

    await TeamsClient(credentials).send_direct_message(address="ana@q99.ai", text="hello")

    chat_call = next(call for call in calls if call[1].endswith(CHATS))
    members = chat_call[2]["json"]["members"]
    assert [m["user@odata.bind"].endswith("users('me')") for m in members].count(True) == 1
    assert [m["user@odata.bind"].endswith("users('them')") for m in members].count(True) == 1
    assert calls[-1][1].endswith("/chats/chat-1/messages")


async def test_a_direct_message_to_a_stranger_says_so(monkeypatch, credentials):
    """The address is what the person typed, so the error has to name it."""
    _patch_transport(monkeypatch, responses=[(404, {"error": "not found"})])

    with pytest.raises(ResourceNotFound) as raised:
        await TeamsClient(credentials).send_direct_message(address="nadie@q99.ai", text="hello")

    assert "nadie@q99.ai" in str(raised.value)


# Reading


def _wrote(who: str, at: str, content: str, **extra) -> dict:
    message = {
        "messageType": "message",
        "createdDateTime": at,
        "from": {"user": {"displayName": who}},
        "body": {"contentType": HTML_CONTENT, "content": content},
    }
    message.update(extra)
    return message


async def test_a_channel_is_asked_for_its_latest_messages(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[(200, {"value": [_wrote("Ana", "2026-08-26T10:00:00Z", "<p>ya salió</p>")]})],
    )

    said = await TeamsClient(credentials).channel_messages(team_id="t1", channel_id="c1")

    assert said == [{"from": "Ana", "at": "2026-08-26T10:00:00Z", "text": "ya salió"}]
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url.endswith("/teams/t1/channels/c1/messages")
    assert kwargs["params"]["$top"] == str(HISTORY_LIMIT)


async def test_what_teams_keeps_in_the_thread_that_nobody_said_is_dropped(monkeypatch, credentials):
    """Joins, renames and deletions live in the same list as the conversation."""
    _patch_transport(
        monkeypatch,
        responses=[
            (
                200,
                {
                    "value": [
                        _wrote("Ana", "2026-08-26T10:00:00Z", "esto sí"),
                        {"messageType": "systemEventMessage", "createdDateTime": "2026-08-26T09:00:00Z"},
                        _wrote("Beto", "2026-08-26T08:00:00Z", "borrado", deletedDateTime="2026-08-26T08:01:00Z"),
                        _wrote("Ana", "2026-08-26T07:00:00Z", "<div><img src='x'></div>"),
                    ]
                },
            )
        ],
    )

    said = await TeamsClient(credentials).channel_messages(team_id="t1", channel_id="c1")

    assert [one["text"] for one in said] == ["esto sí"]


async def test_a_message_arrives_as_html_and_leaves_as_text(monkeypatch, credentials):
    _patch_transport(
        monkeypatch,
        responses=[
            (
                200,
                {
                    "value": [
                        _wrote(
                            "Ana",
                            "2026-08-26T10:00:00Z",
                            "<p>hola <at id='0'>Beto</at>,</p><p>&iquest;lo vemos hoy&nbsp;?</p>",
                        )
                    ]
                },
            )
        ],
    )

    said = await TeamsClient(credentials).channel_messages(team_id="t1", channel_id="c1")

    assert said[0]["text"] == "hola Beto, ¿lo vemos hoy?"


async def test_the_history_comes_back_newest_first(monkeypatch, credentials):
    """Ordered here and not trusted from Graph: the question is what was said last."""
    _patch_transport(
        monkeypatch,
        responses=[
            (
                200,
                {
                    "value": [
                        _wrote("Ana", "2026-08-24T10:00:00Z", "vieja"),
                        _wrote("Beto", "2026-08-26T10:00:00Z", "nueva"),
                    ]
                },
            )
        ],
    )

    said = await TeamsClient(credentials).channel_messages(team_id="t1", channel_id="c1")

    assert [one["text"] for one in said] == ["nueva", "vieja"]


async def test_a_chat_history_is_resolved_the_same_way_sending_is(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (200, {"id": "them"}),
            (200, {"id": "me"}),
            (201, {"id": "chat-1"}),
            (200, {"value": [_wrote("Ana", "2026-08-26T10:00:00Z", "hola")]}),
        ],
    )

    said = await TeamsClient(credentials).chat_messages(address="ana@q99.ai")

    assert [one["text"] for one in said] == ["hola"]
    assert calls[-1][1].endswith("/chats/chat-1/messages")


async def test_a_search_asks_the_search_api_for_chat_messages(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (
                200,
                {
                    "value": [
                        {
                            "hitsContainers": [
                                {"hits": [{"resource": _wrote("Ana", "2026-08-26T10:00:00Z", "el pozo 12")}]}
                            ]
                        }
                    ]
                },
            )
        ],
    )

    said = await TeamsClient(credentials).search_messages("pozo 12")

    assert [one["text"] for one in said] == ["el pozo 12"]
    method, url, kwargs = calls[0]
    assert method == "POST"
    assert url.endswith(SEARCH_QUERY)
    request = kwargs["json"]["requests"][0]
    assert request["entityTypes"] == ["chatMessage"]
    assert request["query"]["queryString"] == "pozo 12"
    assert request["size"] == SEARCH_LIMIT


async def test_an_empty_search_asks_graph_nothing(monkeypatch, credentials):
    calls = _patch_transport(monkeypatch, responses=[])

    assert await TeamsClient(credentials).search_messages("   ") == []
    assert calls == []


# Refresh


async def test_a_401_refreshes_once_and_retries(monkeypatch, credentials):
    calls = _patch_transport(
        monkeypatch,
        responses=[
            (401, {"error": "expired"}),
            (200, {"access_token": "fresh-token", "refresh_token": "refresh-2"}),
            (201, {"id": "m1"}),
        ],
    )

    await TeamsClient(credentials).send_channel_message(
        team_id="t1", channel_id="c1", text="hello"
    )

    assert len(_token_calls(calls)) == 1
    assert calls[-1][1].endswith("/teams/t1/channels/c1/messages")


async def test_a_refresh_reaches_the_host_so_it_can_be_stored(monkeypatch, credentials):
    """Microsoft rotates the refresh token on use; one that is not written back
    leaves the stored credential dead."""
    _patch_transport(
        monkeypatch,
        responses=[
            (401, {"error": "expired"}),
            (200, {"access_token": "fresh-token", "refresh_token": "refresh-2"}),
            (200, {"value": []}),
        ],
    )
    stored: list = []

    async def store(creds):
        stored.append((creds.api_key, creds.refresh_token))

    await TeamsClient(credentials, on_refresh=store).joined_teams()

    assert stored == [("fresh-token", "refresh-2")]


async def test_credentials_without_a_token_are_refused_before_any_request():
    with pytest.raises(ValueError):
        TeamsClient(OnboardingData(source=SourceEnum.teams))
