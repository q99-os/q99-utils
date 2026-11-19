"""Username/password connection test for Datawell and Wellprod installations."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx

from q99_utils.integrations.core.exceptions import CredentialValidationError
from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.models import OnboardingData


def api_base_url(value: str | None, source: str) -> str:
    """Accept a product API root, including one pasted from its Swagger page."""
    if not value or not value.strip():
        raise CredentialValidationError(f"{source} requires an API base URL.", source=source)
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError("Invalid API base URL")
        _ = parsed.port
        path = parsed.path.rstrip("/")
        is_swagger_url = False
        for suffix in ("/swagger-ui/index.html", "/swagger-ui", "/v3/api-docs"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                is_swagger_url = True
                break
        if parsed.fragment and not is_swagger_url:
            raise ValueError("Invalid API base URL")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    except ValueError:
        raise CredentialValidationError(
            f"{source} requires an HTTPS API base URL.",
            source=source,
        ) from None


class DccsoftConnectionIntegration(SourceIntegrationInterface):
    async def test_connection(self, data: OnboardingData | None = None) -> None:
        credentials = data if data is not None else await self.get_credentials()
        source = str(self.source)
        if not credentials.username or not credentials.password:
            raise CredentialValidationError(
                f"{source} requires a username and password.", source=source,
            )
        base_url = api_base_url(credentials.api_base, source)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                response = await client.post(
                    f"{base_url}/api/auth/login",
                    json={"username": credentials.username, "password": credentials.password},
                )
                if response.status_code in (401, 403):
                    raise CredentialValidationError(
                        f"{source} rejected the username or password.", source=source,
                    )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("token"), str) or not body["token"].strip():
                    raise ValueError("Missing authentication token")
        except CredentialValidationError:
            raise
        except (httpx.HTTPError, ValueError):
            raise CredentialValidationError(
                f"{source} connection test failed. Check the API base URL and credentials.",
                source=source,
            ) from None
