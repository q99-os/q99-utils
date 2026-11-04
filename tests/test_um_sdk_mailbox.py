"""The engine reads, from the User Manager, which groups may see mailbox files."""

import httpx

from q99_utils.environment import USER_MANAGER_URL
from q99_utils.models import MAILBOX_FILES_PERMISSION
from q99_utils.um_sdk import UserManagerSDK


async def test_um_sdk_reads_mailbox_file_permissions():
    requested = []

    class FakeClient:
        async def request(self, method, url, **kwargs):
            requested.append((method, url, kwargs["headers"]))
            return httpx.Response(
                200, json={"permissions": ["quantos:group:ops"]}, request=httpx.Request(method, url)
            )

    sdk = UserManagerSDK(api_key="k-1")
    sdk._client = FakeClient()

    assert await sdk.get_mailbox_file_permissions() == ["quantos:group:ops"]
    assert requested == [("GET", f"{USER_MANAGER_URL}/v1/mailbox/file-permissions/", {"Authorization": "Api-Key k-1"})]


async def test_um_sdk_reports_unmatched_mailbox_files():
    requested = []

    class FakeClient:
        async def request(self, method, url, **kwargs):
            requested.append((method, url, kwargs["json"], kwargs["headers"]))
            return httpx.Response(201, json={"created": 2}, request=httpx.Request(method, url))

    sdk = UserManagerSDK(api_key="k-1")
    sdk._client = FakeClient()

    assert await sdk.notify_mailbox_unmatched("cred-1", ["a.pdf", "b.docx"]) == {"created": 2}
    assert requested == [(
        "POST",
        f"{USER_MANAGER_URL}/v1/mailbox/unmatched-files/",
        {"credential_id": "cred-1", "files": ["a.pdf", "b.docx"]},
        {"Authorization": "Api-Key k-1"},
    )]


def test_mailbox_permission_is_a_valid_engine_codename():
    # The engine's catalog only accepts "<resource>:<action>" with a known action.
    assert MAILBOX_FILES_PERMISSION == "files.mailbox:read"
