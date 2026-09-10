"""Client for the wells service.

Deliberately thin: one generic resource wrapper instead of a method per endpoint, and
dicts in and out instead of mirrored models. A schema change in the service costs
nothing here — only a *new resource* is a change to this file, which is what keeps
version bumps rare.

    wells = WellsSDK(access_token=token)
    pad   = await wells.pads.create({"name": "PAD 25", "field_id": fid})
    plans = await wells.pad_plans.list(pad_id=pad["id"])
    await wells.plan_phases.update(phase_id, {"md_base_m": 2500})
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, status

from q99_utils.environment import WELLS_URL

# Every resource the service exposes, as its URL segment. Adding one is a one-line change.
_RESOURCES = [
    "fields", "pads", "wells",
    "phase-types", "activities", "formations", "providers", "service-groups",
    "bits", "casings",
    "pad-plans", "well-plans", "plan-phases", "plan-bits", "plan-casings",
    "plan-activities", "plan-formation-tops", "plan-trajectory-points",
    "rates", "plan-rates", "cost-lines",
]


class _Resource:
    """CRUD over one collection. Attribute name is the segment with dashes as underscores."""

    def __init__(self, sdk: "WellsSDK", segment: str) -> None:
        self._sdk = sdk
        self._base = f"{WELLS_URL}/v1/{segment}/"

    async def list(self, **params: Any) -> list[dict]:
        return await self._sdk._request("GET", self._base, params=params or None)

    async def get(self, row_id: str) -> dict:
        return await self._sdk._request("GET", f"{self._base}{row_id}/")

    async def view(self, row_id: str, name: str) -> Any:
        """A computed view of one row — `pad_plans.view(id, "schedule")`. Views are reads over
        a resource, not resources, so they answer whatever shape the service publishes."""
        return await self._sdk._request("GET", f"{self._base}{row_id}/{name}/")

    async def action(self, row_id: str, name: str, data: dict | None = None) -> Any:
        """POST an action on one row — `pad_plans.action(id, "fill")` runs the compute."""
        return await self._sdk._request("POST", f"{self._base}{row_id}/{name}/", json=data)

    async def replace(self, row_id: str, name: str, data: dict) -> Any:
        """PUT a sub-collection of one row wholesale — `rates.replace(id, "activities", …)`
        sends the whole set it wants, not a diff."""
        return await self._sdk._request("PUT", f"{self._base}{row_id}/{name}/", json=data)

    async def create(self, data: dict | list[dict]) -> dict | list[dict]:
        """The payload goes as given: the high-volume child collections take a list and write it
        in one transaction, every other collection takes a single object."""
        return await self._sdk._request("POST", self._base, json=data)

    async def update(self, row_id: str, data: dict) -> dict:
        return await self._sdk._request("PATCH", f"{self._base}{row_id}/", json=data)

    async def delete(self, row_id: str) -> None:
        return await self._sdk._request("DELETE", f"{self._base}{row_id}/")


def _as_error(response: httpx.Response) -> HTTPException:
    """Wells' own sentence for the caller's mistakes; one of ours for anything that is the
    service's or this deployment's problem. A wells 401 is the CALLER'S service key, never
    the end user's session, so it must not reach a browser as one."""
    code = response.status_code
    if code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail="The caller is not authorized to the wells service — check its service key.")
    if code == status.HTTP_429_TOO_MANY_REQUESTS or code >= 500:
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail="The wells service is busy — try again in a moment.")
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("detail") if isinstance(body, dict) else body
    return HTTPException(status_code=code,
                         detail=detail if isinstance(detail, str) else "The wells service rejected the request.")


class WellsSDK:
    def __init__(self, access_token: str | None = None, *, api_key: str | None = None) -> None:
        if access_token and api_key:
            raise ValueError("Pass either access_token or api_key, not both")
        self.access_token = access_token
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30.0)
        for segment in _RESOURCES:
            setattr(self, segment.replace("-", "_"), _Resource(self, segment))

    async def _request(self, method: str, url: str, params: dict | None = None,
                       json: dict | None = None):
        headers = {}
        if self.access_token:
            headers["Authorization"] = self.access_token
        elif self.api_key:
            headers["Authorization"] = f"Api-Key {self.api_key}"

        try:
            response = await self._client.request(method, url, headers=headers,
                                                  params=params, json=json)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Wells service unavailable: {exc}",
            )

        if response.status_code >= 400:
            raise _as_error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def healthcheck(self) -> dict:
        return await self._request("GET", f"{WELLS_URL}/healthcheck/")

    async def aclose(self) -> None:
        await self._client.aclose()
