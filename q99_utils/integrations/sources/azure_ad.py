"""Azure AD integration — directory reads and change-notification subscriptions.

Everything here runs app-only: the credential is a registered application, not
a signed-in user, so the same call works for any user or group in the tenant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from q99_utils.integrations.core import (
    GRAPH_BASE_URL,
    CredentialValidationError,
    MicrosoftGraphAuth,
    SourceIntegrationInterface,
    graph_paginate,
    graph_request,
    register,
)
from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

GRAPH_GROUPS_URL = f"{GRAPH_BASE_URL}/groups"
GRAPH_USERS_URL = f"{GRAPH_BASE_URL}/users"
GRAPH_SUBSCRIPTIONS_URL = f"{GRAPH_BASE_URL}/subscriptions"

GROUP_SELECT = "$select=id,displayName"

MEMBERSHIP_TYPES = frozenset(
    {"#microsoft.graph.group", "#microsoft.graph.directoryRole"}
)


@register(SourceEnum.azure_ad)
class AzureADIntegration(MicrosoftGraphAuth, SourceIntegrationInterface):

    # Credential validation

    async def test_connection(self, data: OnboardingData):
        try:
            access_token = await self.get_access_token(data=data)
        except httpx.HTTPError:
            logger.warning("Azure AD token acquisition failed", exc_info=True)
            raise CredentialValidationError(
                "Azure AD authentication failed: could not acquire access token. "
                "Verify client_id, client_secret, and tenant_id are correct.",
                source=str(self.source),
            )

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(
                    GRAPH_GROUPS_URL,
                    headers=headers,
                    params={"$top": "1"},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Azure AD connection test failed", exc_info=True)
            raise CredentialValidationError(
                "Azure AD connection test failed: could not access Microsoft Graph groups endpoint. "
                "Verify the app has the required Group.Read.All permission.",
                source=str(self.source),
            )

    # Groups

    async def fetch_all_groups(self, data: Optional[OnboardingData] = None) -> List[Dict[str, str]]:
        """Every group in the tenant as ``{id, displayName}``.

        The stable id is what lets the caller tell a rename from a new group.
        """
        token = await self.get_access_token(data)
        groups = [
            {"id": g["id"], "displayName": g["displayName"]}
            async for g in graph_paginate(
                access_token=token, url=f"{GRAPH_GROUPS_URL}?{GROUP_SELECT}"
            )
            if g.get("id") and g.get("displayName")
        ]
        logger.info("Fetched %d groups from Azure AD", len(groups))
        return groups

    async def fetch_group_by_id(
        self, group_id: str, data: Optional[OnboardingData] = None
    ) -> Dict[str, str]:
        """One group. Raises ``ResourceNotFound`` when it is gone."""
        token = await self.get_access_token(data)
        payload = await graph_request(
            access_token=token, url=f"{GRAPH_GROUPS_URL}/{group_id}?{GROUP_SELECT}"
        )
        return {"id": payload.get("id"), "displayName": payload.get("displayName")}

    async def fetch_group_members(
        self, group_id: str, data: Optional[OnboardingData] = None
    ) -> List[str]:
        """Member emails, lowercased.

        Members with neither ``mail`` nor ``userPrincipalName`` — nested groups,
        typically — are skipped rather than reported as blanks.
        """
        token = await self.get_access_token(data)
        url = f"{GRAPH_GROUPS_URL}/{group_id}/members?$select=mail,userPrincipalName"
        emails = [
            email.lower()
            async for m in graph_paginate(access_token=token, url=url)
            if (email := m.get("mail") or m.get("userPrincipalName"))
        ]
        logger.info("Fetched %d members for group %s", len(emails), group_id)
        return emails

    # Users

    async def fetch_all_user_emails(self, data: Optional[OnboardingData] = None) -> List[str]:
        """Every tenant user's email, lowercased. Needs ``User.Read.All``."""
        token = await self.get_access_token(data)
        emails = [
            mail.lower()
            async for u in graph_paginate(
                access_token=token, url=f"{GRAPH_USERS_URL}?$select=mail"
            )
            if (mail := u.get("mail"))
        ]
        logger.info("Fetched %d user emails from Azure AD", len(emails))
        return emails

    async def fetch_user_memberships(
        self, email: str, data: Optional[OnboardingData] = None
    ) -> List[Dict[str, str]]:
        """A user's groups and directory roles as ``{id, displayName}``.

        Raises ``ResourceNotFound`` when the user does not exist.
        """
        token = await self.get_access_token(data)
        url = f"{GRAPH_USERS_URL}/{email}/memberOf"
        memberships = [
            {"id": item["id"], "displayName": item["displayName"]}
            async for item in graph_paginate(access_token=token, url=url)
            if item.get("@odata.type") in MEMBERSHIP_TYPES
            and item.get("id")
            and item.get("displayName")
        ]
        logger.info("Fetched %d groups for user %s", len(memberships), email)
        return memberships

    async def fetch_user_group_names(
        self, email: str, data: Optional[OnboardingData] = None
    ) -> List[str]:
        """Just the names, for callers that match on name alone."""
        return [g["displayName"] for g in await self.fetch_user_memberships(email, data)]

    # Change notifications

    async def create_subscription(
        self,
        *,
        resource: str,
        change_type: str,
        notification_url: str,
        client_state: str,
        expiration: str,
        lifecycle_url: Optional[str] = None,
        data: Optional[OnboardingData] = None,
    ) -> Dict[str, Any]:
        token = await self.get_access_token(data)
        payload = {
            "changeType": change_type,
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration,
            "clientState": client_state,
        }
        if lifecycle_url:
            payload["lifecycleNotificationUrl"] = lifecycle_url

        return await graph_request(
            access_token=token, url=GRAPH_SUBSCRIPTIONS_URL, method="POST", json=payload
        )

    async def renew_subscription(
        self, subscription_id: str, expiration: str, data: Optional[OnboardingData] = None
    ) -> Dict[str, Any]:
        token = await self.get_access_token(data)
        return await graph_request(
            access_token=token,
            url=f"{GRAPH_SUBSCRIPTIONS_URL}/{subscription_id}",
            method="PATCH",
            json={"expirationDateTime": expiration},
        )

    async def delete_subscription(
        self, subscription_id: str, data: Optional[OnboardingData] = None
    ) -> None:
        token = await self.get_access_token(data)
        await graph_request(
            access_token=token,
            url=f"{GRAPH_SUBSCRIPTIONS_URL}/{subscription_id}",
            method="DELETE",
        )

    async def list_subscriptions(
        self, data: Optional[OnboardingData] = None
    ) -> List[Dict[str, Any]]:
        token = await self.get_access_token(data)
        payload = await graph_request(access_token=token, url=GRAPH_SUBSCRIPTIONS_URL)
        return payload.get("value") or []


__all__ = ["AzureADIntegration"]
