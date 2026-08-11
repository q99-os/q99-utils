from __future__ import annotations

import httpx

from q99_utils.integrations.core import SourceIntegrationInterface, register
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

PROD_API_URL = "https://api.green-api.com"
SANDBOX_API_URL = "https://7107.api.green-api.com"
MEDIA_API_URL = "https://media.green-api.com"


def resolve_api_url(environment: str) -> str:
    """GreenAPI base URL for a deployment environment.

    Only production talks to the production instance; everything else, stage
    and sandbox included, goes to the sandbox. Consumers outside the engine
    call this directly — they have an environment name but no
    ``IntegrationContext`` to read it from.
    """
    return PROD_API_URL if environment == "prod" else SANDBOX_API_URL


@register(SourceEnum.greenapi, SourceEnum.greenapi_partner)
class GreenAPIIntegration(SourceIntegrationInterface):

    @property
    def api_url(self) -> str:
        """GreenAPI base URL for the current deployment.

        Resolved per instance from the injected config; it used to be a class
        attribute evaluated against the host's settings at import time, which
        made the module impossible to import without the host's environment.
        """
        return resolve_api_url(self.config.environment)

    async def api_status(self, data: OnboardingData) -> bool:

        url = f"{self.api_url}/waInstance{data.instance_id}/getStateInstance/{data.api_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url=url)
            response.raise_for_status()
            payload = response.json()
            return payload.get("stateInstance") == "authorized"

    async def get_instances(self, data: OnboardingData):
        url = f"{self.api_url}/partner/getInstances/{data.partner_token}"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url=url)
            response.raise_for_status()
            return response.json()

    async def create_instance(self, partner_token: str, data: OnboardingData) -> dict:
        url = f"{self.api_url}/partner/createInstance/{partner_token}"
        payload = {
            "webhookUrl": f"{self.config.webhook_base_url}/greenapi/webhook",
            "name": data.instance_name,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def get_qr_code(self, data: OnboardingData):
        url = f"{self.api_url}/waInstance{data.instance_id}/qr/{data.api_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url)
            resp.raise_for_status()
            return resp.json()


__all__ = [
    "MEDIA_API_URL",
    "PROD_API_URL",
    "SANDBOX_API_URL",
    "GreenAPIIntegration",
    "resolve_api_url",
]
