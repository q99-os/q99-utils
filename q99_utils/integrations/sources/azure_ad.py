from __future__ import annotations

import httpx

from q99_utils.integrations.core import CredentialValidationError, SourceIntegrationInterface, register
from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_GROUPS_URL = "https://graph.microsoft.com/v1.0/groups"


@register(SourceEnum.azure_ad)
class AzureADIntegration(SourceIntegrationInterface):

    async def get_access_token(self, data: OnboardingData = None):
        if data:
            self.credentials = data.model_dump()
        else:
            await self.get_credentials()

        tenant_id = self.credentials["tenant_id"]
        client_id = self.credentials["client_id"]
        client_secret = self.credentials["client_secret"]

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        token_data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": GRAPH_SCOPE,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(token_url, data=token_data)
            response.raise_for_status()
            token = response.json().get("access_token")

        return token

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


__all__ = ["AzureADIntegration"]
