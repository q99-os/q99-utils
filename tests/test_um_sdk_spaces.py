"""A space's tiles are read as their owner and saved by Quantos for them, on top of the version read;
a new space is named with the service key, and a new Spaces chat can be held on a space."""

import httpx
import pytest
from fastapi import HTTPException, status

from q99_utils.environment import USER_MANAGER_URL
from q99_utils.models import UMMessage
from q99_utils.um_sdk import UserManagerSDK


def _sdk(code: int, body: dict, requested: list, **auth) -> UserManagerSDK:
    class FakeClient:
        async def request(self, method, url, **kwargs):
            requested.append((method, url, kwargs["headers"], kwargs["json"]))
            return httpx.Response(code, json=body, request=httpx.Request(method, url))

    sdk = UserManagerSDK(**auth)
    sdk._client = FakeClient()
    return sdk


async def test_a_space_is_read_saved_and_named_at_its_id():
    requested = []
    space = {"tiles": [], "version": 3}
    assert await _sdk(status.HTTP_200_OK, space, requested, access_token="Bearer t").get_space("c-1") == space
    await _sdk(status.HTTP_200_OK, space, requested, api_key="k-1").save_space_tiles("c-1", [{"id": "t_1"}], 3)
    await _sdk(status.HTTP_200_OK, space, requested, api_key="k-1").name_space("c-1", "Water", {"icon": "droplets", "tone": 1, "pattern": 0})
    url = f"{USER_MANAGER_URL}/v1/spaces/c-1/"
    assert requested == [
        ("GET", url, {"Authorization": "Bearer t"}, None),
        ("PATCH", url, {"If-Match": "3", "Authorization": "Api-Key k-1"}, {"tiles": [{"id": "t_1"}]}),
        ("PATCH", url, {"Authorization": "Api-Key k-1"}, {"title": "Water", "symbol": {"icon": "droplets", "tone": 1, "pattern": 0}}),
    ]


async def test_tiles_saved_on_a_stale_read_are_a_412():
    with pytest.raises(HTTPException) as refused:
        await _sdk(status.HTTP_412_PRECONDITION_FAILED, {"code": "revision_conflict", "revision": 5}, [], api_key="k-1").save_space_tiles("c-1", [], 3)
    assert refused.value.status_code == status.HTTP_412_PRECONDITION_FAILED


async def test_a_new_spaces_chat_names_the_space_it_is_held_on():
    requested = []
    sdk = _sdk(status.HTTP_201_CREATED, {"id": "i-1"}, requested, access_token="Bearer t")
    await sdk.add_interaction(UMMessage(type="Question", content="q"), feature="spaces", space_id="s-1")
    assert requested[0][3]["space"] == "s-1" and requested[0][3]["feature"] == "spaces"


async def test_a_branch_is_named_on_its_first_question():
    requested = []
    await _sdk(status.HTTP_200_OK, {}, requested, access_token="Bearer t").name_branch("m-1", "Costs by well")
    assert requested == [("POST", f"{USER_MANAGER_URL}/v1/messages/m-1/branch-title/", {"Authorization": "Bearer t"}, {"title": "Costs by well", "if_unnamed": True})]
