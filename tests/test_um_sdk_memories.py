"""A person's memories reach UM with their own token, and UM's refusals come back as they are."""

import json

import httpx
import pytest
from fastapi import HTTPException, status

from q99_utils.um_sdk import UserManagerSDK

UM = "http://um.test/um"


@pytest.fixture
def um(monkeypatch):
    monkeypatch.setattr("q99_utils.um_sdk.USER_MANAGER_URL", UM)
    requests = []

    def use(answer):
        def handler(request):
            requests.append(request)
            return answer(request)

        sdk = UserManagerSDK("Bearer alice")
        sdk._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return sdk

    return use, requests


async def test_saving_sends_the_memory_with_the_persons_token(um):
    use, requests = um
    saved = {"id": "m1", "kind": "memory", "name": "pressure-units", "description": "Shows pressure in PSI",
             "content": "Always show pressure in PSI."}
    sdk = use(lambda request: httpx.Response(status.HTTP_201_CREATED, json=saved))

    answer = await sdk.save_memory("memory", "pressure-units", "Shows pressure in PSI", "Always show pressure in PSI.")

    assert answer == saved
    assert (requests[0].method, str(requests[0].url)) == ("POST", f"{UM}/v1/memories/")
    assert requests[0].headers["Authorization"] == "Bearer alice"
    assert json.loads(requests[0].content) == {"kind": "memory", "name": "pressure-units",
                                               "description": "Shows pressure in PSI",
                                               "content": "Always show pressure in PSI."}


async def test_listing_asks_for_one_kind_only_when_given(um):
    use, requests = um
    sdk = use(lambda request: httpx.Response(status.HTTP_200_OK, json=[]))

    await sdk.list_memories()
    await sdk.list_memories(kind="workflow")

    await sdk.list_memories(in_use=True)

    assert [str(request.url) for request in requests] == [f"{UM}/v1/memories/", f"{UM}/v1/memories/?kind=workflow",
                                                          f"{UM}/v1/memories/?in_use=1"]


async def test_deleting_reaches_that_memory(um):
    use, requests = um
    sdk = use(lambda request: httpx.Response(status.HTTP_204_NO_CONTENT))

    deleted = await sdk.delete_memory("m1")

    assert deleted is None
    assert [(request.method, str(request.url)) for request in requests] == [("DELETE", f"{UM}/v1/memories/m1/")]


async def test_someone_elses_memory_comes_back_as_not_found(um):
    use, _ = um
    sdk = use(lambda request: httpx.Response(status.HTTP_404_NOT_FOUND, json={"detail": "Not found."}))

    with pytest.raises(HTTPException) as raised:
        await sdk.delete_memory("m1")

    assert raised.value.status_code == status.HTTP_404_NOT_FOUND


async def test_a_branch_is_read_whole_with_its_owners_memories(um):
    use, requests = um
    branch = {"id": "c1", "chats": [], "memories": [{"kind": "memory", "name": "pressure-units",
                                                     "description": "Shows pressure in PSI",
                                                     "content": "Always show pressure in PSI."}]}
    sdk = use(lambda request: httpx.Response(status.HTTP_200_OK, json=branch))

    answer = await sdk.get_branch_history("i1")

    assert answer == branch
    assert (requests[0].method, str(requests[0].url)) == ("GET", f"{UM}/v1/history/conversation/i1/context/")
    assert requests[0].headers["Authorization"] == "Bearer alice"


async def test_switching_a_workflow_posts_on_or_off(um):
    use, requests = um
    sdk = use(lambda request: httpx.Response(status.HTTP_200_OK, json={"id": "w1", "on": False}))

    await sdk.switch_workflow("w1", False)

    assert (requests[0].method, str(requests[0].url)) == ("POST", f"{UM}/v1/memories/w1/switch/")
    assert json.loads(requests[0].content) == {"on": False}
