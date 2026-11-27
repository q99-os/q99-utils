"""Resetting a discovery cursor must not claim a successful sync."""

import httpx

from q99_utils.um_sdk import UserManagerSDK


async def test_reset_sync_cursor_does_not_stamp_last_sync():
    requests = []

    class FakeClient:
        async def request(self, method, url, **kwargs):
            requests.append((method, kwargs["json"]))
            return httpx.Response(200, json={}, request=httpx.Request(method, url))

    sdk = UserManagerSDK(api_key="service-key")
    sdk._client = FakeClient()

    await sdk.update_sync_state("credential-id", sync_cursors={})
    await sdk.update_sync_state("credential-id", sync_cursors={"page": 2}, last_sync="2026-11-26T00:00:00Z")

    assert requests == [
        ("PATCH", {"sync_cursors": {}}),
        ("PATCH", {"sync_cursors": {"page": 2}, "last_sync": "2026-11-26T00:00:00Z"}),
    ]
