"""Read-only client for Mirico's Analysis Engine API.

Mirico's production and staging APIs use HTTP bearer authentication and an
``/engine-api`` server prefix. An API key is required for every data request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

import httpx

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.core.registry import register
from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.models import OnboardingData


DEFAULT_API_BASE = "https://api.mirico.com/engine-api"
STAGING_API_BASE = "https://api.mirico.dev/engine-api"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
ResponseKind = Literal["list", "object", "optional_object"]


def _api_base(value: str | None) -> str:
    base = (value or DEFAULT_API_BASE).strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CredentialValidationError(
            "Mirico API Base must be an HTTPS URL without credentials, query, or fragment.",
            source="mirico",
        )
    return base


def _deployment_path(deployment_id: int, suffix: str = "") -> str:
    if type(deployment_id) is not int or deployment_id < 1:
        raise ValueError("Mirico deployment_id must be a positive integer.")
    return f"/deployments/{deployment_id}{suffix}"


def _timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("Mirico time values must be datetimes or ISO 8601 strings.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Mirico time values must be ISO 8601 timestamps.") from None


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _window(start: datetime | str, end: datetime | str, *, raw: bool = False) -> dict[str, str]:
    first = _timestamp(start)
    last = _timestamp(end)
    if (first.tzinfo is None) != (last.tzinfo is None):
        raise ValueError("Mirico time values must use the same timezone convention.")
    first = _naive_utc(first)
    last = _naive_utc(last)
    if last <= first:
        raise ValueError("Mirico end time must be after start time.")
    if raw:
        return {"datetime_from": first.isoformat(), "datetime_to": last.isoformat()}
    return {"start_time": first.isoformat(), "end_time": last.isoformat()}


@register(SourceEnum.mirico)
class MiricoIntegration(SourceIntegrationInterface):
    async def _get(
        self,
        path: str,
        data: OnboardingData | None = None,
        *,
        params: Mapping[str, str] | None = None,
        kind: ResponseKind = "list",
    ) -> Any:
        credentials = data if data is not None else await self.get_credentials()
        key = credentials.api_key
        if not key or not key.strip():
            raise CredentialValidationError("Mirico requires an API key.", source="mirico")
        base = _api_base(credentials.api_base)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{base}{path}",
                params=params,
                headers={"Authorization": f"Bearer {key.strip()}", "Accept": "application/json"},
            )
        if response.status_code in (401, 403):
            raise CredentialValidationError(
                "Mirico rejected the API key or denied access to the requested data.",
                source="mirico",
            )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            raise IntegrationError("Mirico returned a non-JSON response.") from None
        if kind == "list" and (not isinstance(body, list) or any(not isinstance(row, dict) for row in body)):
            raise IntegrationError("Mirico returned an invalid data list.")
        if kind == "object" and not isinstance(body, dict):
            raise IntegrationError("Mirico returned an invalid data object.")
        if kind == "optional_object" and body is not None and not isinstance(body, dict):
            raise IntegrationError("Mirico returned an invalid status object.")
        return body

    async def test_connection(self, data: OnboardingData | None = None) -> None:
        """A small authorized read also works when the user has no sites yet."""
        try:
            await self.list_sites(data=data)
        except CredentialValidationError:
            raise
        except (httpx.HTTPError, IntegrationError):
            raise CredentialValidationError(
                "Mirico connection test failed. Check your API key and site access or contact support.",
                source="mirico",
            ) from None

    async def list_sites(self, data: OnboardingData | None = None) -> list[dict]:
        return await self._get("/deployments/sites", data=data)

    async def list_deployments(self, data: OnboardingData | None = None) -> list[dict]:
        return await self._get("/deployments/", data=data)

    async def get_deployment(self, deployment_id: int, data: OnboardingData | None = None) -> dict:
        return await self._get(_deployment_path(deployment_id), data=data, kind="object")

    async def get_instrument_status(self, deployment_id: int, data: OnboardingData | None = None) -> dict | None:
        return await self._get(
            _deployment_path(deployment_id, "/instrument-status/latest"), data=data, kind="optional_object"
        )

    async def get_site_limits(self, deployment_id: int, data: OnboardingData | None = None) -> dict:
        return await self._get(_deployment_path(deployment_id, "/site-limits"), data=data, kind="object")

    async def get_targets(self, deployment_id: int, data: OnboardingData | None = None) -> list[dict]:
        return await self._get(_deployment_path(deployment_id, "/targets"), data=data)

    async def get_readings(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(_deployment_path(deployment_id, "/readings"), data=data, params=_window(start, end))

    async def get_tse(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(_deployment_path(deployment_id, "/tse"), data=data, params=_window(start, end))

    async def get_tse_daily_aggregate(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/tse-daily-aggregate"), data=data, params=_window(start, end)
        )

    async def get_lq_clustering(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/lq-output/clustering"), data=data, params=_window(start, end)
        )

    async def get_lq_kde(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/lq-output/kde"), data=data, params=_window(start, end)
        )

    async def get_zone_emissions(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/total-zone-emissions"), data=data, params=_window(start, end)
        )

    async def get_detections(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(_deployment_path(deployment_id, "/detections"), data=data, params=_window(start, end))

    async def get_coverage(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(_deployment_path(deployment_id, "/coverage"), data=data, params=_window(start, end))

    async def get_raw_air(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/raw-measurements/air/"), data=data,
            params=_window(start, end, raw=True),
        )

    async def get_raw_concentration(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/raw-measurements/concentration/"), data=data,
            params=_window(start, end, raw=True),
        )

    async def get_raw_wind(
        self, deployment_id: int, start: datetime | str, end: datetime | str,
        data: OnboardingData | None = None,
    ) -> list[dict]:
        return await self._get(
            _deployment_path(deployment_id, "/raw-measurements/wind/"), data=data,
            params=_window(start, end, raw=True),
        )


__all__ = ["MiricoIntegration", "DEFAULT_API_BASE", "STAGING_API_BASE"]
