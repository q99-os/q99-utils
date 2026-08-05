from __future__ import annotations

import httpx

from q99_utils.integrations.core import SourceIntegrationInterface, register
from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"


@register(SourceEnum.slack)
class SlackIntegration(SourceIntegrationInterface):

    async def api_status(self, data: OnboardingData) -> bool:
        """Whether the token authenticates against Slack.

        Slack answers most auth failures with HTTP 200 and ``ok: false``, so the
        status code alone isn't enough.
        """
        headers = {"Authorization": f"Bearer {data.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(SLACK_AUTH_TEST_URL, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            logger.warning("Slack auth.test request failed", exc_info=True)
            return False
        except ValueError:  # json.JSONDecodeError — non-JSON body
            logger.warning("Slack auth.test returned a non-JSON body", exc_info=True)
            return False

        if not payload.get("ok"):
            logger.warning("Slack rejected the token: %s", payload.get("error"))
            return False

        return True


__all__ = ["SlackIntegration"]
