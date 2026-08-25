"""Microsoft Teams integration — finding where to write, and writing there.

Delegated only, and not by preference: Graph has no application permission for
posting to a channel, and the one it lists for chats is the migration grant, which
carries its own approval and per-message billing. So every message leaves under the
name of whoever connected their account, and what they can reach is what Teams
already lets them reach.

The transport is the shared delegated client. What lives here is the handful of
endpoints Teams needs and the shape of a ``chatMessage``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from q99_utils.integrations.core import (
    DELEGATED_TEAMS_SCOPES,
    GRAPH_BASE_URL,
    DelegatedGraphClient,
    IntegrationError,
    ResourceNotFound,
    SourceIntegrationInterface,
    register,
)
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

REQUEST_TIMEOUT = 30

JOINED_TEAMS = "/me/joinedTeams"
TEAM_CHANNELS = "/teams/{team_id}/channels"
CHANNEL_MESSAGES = "/teams/{team_id}/channels/{channel_id}/messages"
CHATS = "/chats"
CHAT_MESSAGES = "/chats/{chat_id}/messages"
USERS = "/users"
USER_BY_ADDRESS = "/users/{address}"
ME = "/me"

EVENTUAL = {"ConsistencyLevel": "eventual"}
SEARCH_LIMIT = 10

HTML_CONTENT = "html"
TEXT_CONTENT = "text"

ONE_ON_ONE = "oneOnOne"
MEMBER_TYPE = "#microsoft.graph.aadUserConversationMember"
OWNER_ROLE = "owner"


def message_body(text: str, *, content_type: str = HTML_CONTENT) -> Dict[str, Any]:
    """A Graph ``chatMessage`` body. Teams spells the type lowercase."""
    return {"body": {"contentType": content_type, "content": text}}


def _named(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The entries that can be shown and then used, as ``{id, name}``.

    One without a display name cannot be offered to a person, and one without an id
    cannot be posted to, so neither is worth returning.
    """
    return [
        {"id": item["id"], "name": item["displayName"]}
        for item in items
        if item.get("id") and item.get("displayName")
    ]


class TeamsClient(DelegatedGraphClient):
    """Reads enough of the directory to address a message, and posts it."""

    refresh_scopes = DELEGATED_TEAMS_SCOPES
    timeout_seconds = REQUEST_TIMEOUT

    async def joined_teams(self) -> List[Dict[str, str]]:
        """The teams this person belongs to."""
        payload = await self.get(JOINED_TEAMS, {"$select": "id,displayName"})
        return _named(payload.get("value") or [])

    async def channels(self, team_id: str) -> List[Dict[str, str]]:
        """The channels of one team."""
        payload = await self.get(
            TEAM_CHANNELS.format(team_id=team_id), {"$select": "id,displayName"}
        )
        return _named(payload.get("value") or [])

    async def send_channel_message(
        self, *, team_id: str, channel_id: str, text: str, content_type: str = HTML_CONTENT
    ) -> Dict[str, Any]:
        return await self.post(
            CHANNEL_MESSAGES.format(team_id=team_id, channel_id=channel_id),
            body=message_body(text, content_type=content_type),
        )

    async def find_people(self, query: str, limit: int = SEARCH_LIMIT) -> List[Dict[str, str]]:
        """People in the directory whose name or address matches.

        Searched rather than prefix-matched, so a surname finds someone the same way
        a first name does. The address comes back because it is what addressing a
        chat needs, and a display name alone identifies nobody.

        Graph only answers ``$search`` on the directory for a client that admits
        eventual consistency, and only while it is also counting — hence the header
        and the ``$count``.
        """
        wanted = (query or "").strip().replace('"', "")
        if not wanted:
            return []

        payload = await self.get(
            USERS,
            {
                "$search": f'"displayName:{wanted}" OR "mail:{wanted}"',
                "$select": "id,displayName,mail,userPrincipalName",
                "$top": str(limit),
                "$count": "true",
            },
            EVENTUAL,
        )

        people = []
        for one in payload.get("value") or []:
            address = one.get("mail") or one.get("userPrincipalName")
            if one.get("displayName") and address:
                people.append({"name": one["displayName"], "address": address})
        return people

    async def user_id(self, address: str) -> str:
        """The directory id behind an address."""
        stranger = ResourceNotFound(
            f"Nobody in the organisation has the address {address}",
            source=str(SourceEnum.teams),
        )
        try:
            payload = await self.get(USER_BY_ADDRESS.format(address=address), {"$select": "id"})
        except ResourceNotFound as missing:
            raise stranger from missing

        found = payload.get("id")
        if not found:
            raise stranger
        return found

    async def me(self) -> str:
        """The directory id of whoever connected this account.

        An empty answer is an ``IntegrationError`` and not a ``KeyError``: the host
        branches on the library's exceptions, and a bare key error reaches the person
        as a stack trace instead of something they can act on.
        """
        payload = await self.get(ME, {"$select": "id"})
        found = payload.get("id")
        if not found:
            raise IntegrationError("Microsoft Graph did not say who this account is")
        return found

    def _member(self, user_id: str) -> Dict[str, Any]:
        return {
            "@odata.type": MEMBER_TYPE,
            "roles": [OWNER_ROLE],
            "user@odata.bind": f"{GRAPH_BASE_URL}/users('{user_id}')",
        }

    async def direct_chat(self, address: str) -> str:
        """The id of the one-on-one chat with that person, opening it if it is new.

        Both sides go in the members list — Graph refuses a one-on-one chat that
        names only the other person. It answers an existing chat rather than a
        duplicate, so asking every time is safe.
        """
        them = await self.user_id(address)
        payload = await self.post(
            CHATS,
            body={
                "chatType": ONE_ON_ONE,
                "members": [self._member(await self.me()), self._member(them)],
            },
        )
        chat_id = payload.get("id")
        if not chat_id:
            raise IntegrationError(f"Microsoft Graph opened no chat with {address}")
        return chat_id

    async def send_direct_message(
        self, *, address: str, text: str, content_type: str = HTML_CONTENT
    ) -> Dict[str, Any]:
        chat_id = await self.direct_chat(address)
        return await self.post(
            CHAT_MESSAGES.format(chat_id=chat_id),
            body=message_body(text, content_type=content_type),
        )


@register(SourceEnum.teams)
class TeamsIntegration(SourceIntegrationInterface):

    async def client(self, data: Optional[OnboardingData] = None) -> TeamsClient:
        """A Teams client that writes back whatever it refreshes.

        Credentials handed in directly belong to a caller that has not stored them
        yet — onboarding — so those do not get persisted.
        """
        if data:
            return TeamsClient(await self.with_company_app(data))

        credentials = await self.with_company_app(await self.get_credentials())
        return TeamsClient(credentials, on_refresh=self.persist_tokens)


__all__ = [
    "CHATS",
    "HTML_CONTENT",
    "JOINED_TEAMS",
    "SEARCH_LIMIT",
    "TEXT_CONTENT",
    "TeamsClient",
    "TeamsIntegration",
    "message_body",
]
