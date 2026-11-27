"""Datawell and Wellprod installations: a username/password login, then views read page by page."""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.models import OnboardingData

LOGIN_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
READ_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

#: Rows per page when reading a view.
PAGE_SIZE = 2000

#: Guards against a server that never returns a short page.
MAX_PAGES = 500


def api_base_url(value: str | None, source: str) -> str:
    """Accept a company URL, product API root, or product Swagger URL."""
    label = source.capitalize()
    if not value or not value.strip():
        raise CredentialValidationError(f"{label} requires an API base URL.", source=source)
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
        expected_path = {"datawell": "/rest", "wellprod": "/wp-rest"}.get(source)
        if expected_path:
            if not path:
                path = expected_path
            elif not path.endswith(expected_path):
                raise CredentialValidationError(
                    f"Enter your company URL without an extra path, or paste the {label} Swagger URL.",
                    source=source,
                )
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    except ValueError:
        raise CredentialValidationError(
            f"{label} requires an HTTPS API base URL.",
            source=source,
        ) from None


class DccsoftConnectionIntegration(SourceIntegrationInterface):
    async def _login(self, client: httpx.AsyncClient, credentials: OnboardingData) -> tuple[str, str]:
        """(base URL, bearer token). Raises httpx errors or ValueError on anything but a rejected login."""
        source = str(self.source)
        label = source.capitalize()
        if not credentials.username or not credentials.password:
            raise CredentialValidationError(
                f"{label} requires a username and password.", source=source,
            )
        base_url = api_base_url(credentials.api_base, source)

        response = await client.post(
            f"{base_url}/api/auth/login",
            json={"username": credentials.username, "password": credentials.password},
        )
        if response.status_code in (401, 403):
            raise CredentialValidationError(
                f"{label} rejected the username or password.", source=source,
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("token"), str) or not body["token"].strip():
            raise ValueError("Missing authentication token")
        return base_url, body["token"]

    async def test_connection(self, data: OnboardingData | None = None) -> None:
        credentials = data if data is not None else await self.get_credentials()
        label = str(self.source).capitalize()
        try:
            async with httpx.AsyncClient(timeout=LOGIN_TIMEOUT) as client:
                await self._login(client, credentials)
        except CredentialValidationError:
            raise
        except (httpx.HTTPError, ValueError):
            raise CredentialValidationError(
                f"{label} connection test failed. Check the API base URL and credentials.",
                source=str(self.source),
            ) from None

    async def read_view(
        self, view: str, data: OnboardingData | None = None, *, page_size: int = PAGE_SIZE,
    ) -> list[dict]:
        """Every row of one view. The API filters nothing, so this is always the whole view."""
        credentials = data if data is not None else await self.get_credentials()
        source = str(self.source)
        label = source.capitalize()
        rows: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=READ_TIMEOUT) as client:
                base_url, token = await self._login(client, credentials)
                logged_in_again = False
                page = 0
                while page < MAX_PAGES:
                    response = await client.get(
                        f"{base_url}/api/vistas/{quote(view, safe='')}/pagina",
                        params={"page": page, "size": page_size},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    # the token lasts hours, so a long read may outlive it once
                    if response.status_code == 401 and not logged_in_again:
                        _, token = await self._login(client, credentials)
                        logged_in_again = True
                        continue
                    if response.status_code in (401, 403):
                        raise CredentialValidationError(
                            f"{label} denied access to view '{view}'.", source=source,
                        )
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                        raise IntegrationError(f"{label} returned an invalid page for view '{view}'.")
                    rows.extend(body)
                    if len(body) < page_size:
                        return rows
                    page += 1
        except IntegrationError:
            raise
        except (httpx.HTTPError, ValueError):
            raise IntegrationError(f"{label} could not read view '{view}'.") from None
        raise IntegrationError(f"{label} view '{view}' did not end within {MAX_PAGES} pages.")
