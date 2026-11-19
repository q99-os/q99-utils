"""The engine writes a report's metadata to the User Manager only on top of the revision it read."""

import httpx
import pytest
from fastapi import HTTPException

from q99_utils.environment import USER_MANAGER_URL
from q99_utils.um_sdk import UserManagerSDK


def _sdk(status: int, body: dict, requested: list) -> UserManagerSDK:
    class FakeClient:
        async def request(self, method, url, **kwargs):
            requested.append((method, url, kwargs["headers"]))
            return httpx.Response(status, json=body, request=httpx.Request(method, url))

    sdk = UserManagerSDK(api_key="k-1")
    sdk._client = FakeClient()
    return sdk


async def test_a_report_update_names_the_revision_it_builds_on():
    requested = []
    await _sdk(200, {"revision": 4}, requested).update_report("r-1", {"metadata": {}}, revision=3)
    await _sdk(200, {"revision": 5}, requested).update_report("r-1", {"title": "T"})
    url = f"{USER_MANAGER_URL}/v1/reports/r-1/"
    assert requested == [("PATCH", url, {"If-Match": "3", "Authorization": "Api-Key k-1"}),
                         ("PATCH", url, {"Authorization": "Api-Key k-1"})]


async def test_a_report_changed_since_it_was_read_is_a_412():
    with pytest.raises(HTTPException) as refused:
        await _sdk(412, {"code": "revision_conflict", "revision": 4}, []).update_report("r-1", {"metadata": {}}, revision=3)
    assert refused.value.status_code == 412 and refused.value.detail["revision"] == 4
