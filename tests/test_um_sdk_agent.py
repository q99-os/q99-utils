import httpx
import pytest

from q99_utils.um_sdk import UserManagerSDK


def capture(sdk):
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        return httpx.Response(200, json={})

    sdk._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return seen


async def test_a_persons_agent_client_sends_their_token_the_engine_key_and_the_agent():
    sdk = UserManagerSDK("user-jwt").as_agent("report.chat", engine_key="engine-key")
    seen = capture(sdk)

    await sdk.update_report_section("s1", {"content": {}})

    assert seen["headers"]["authorization"] == "user-jwt"
    assert seen["headers"]["x-engine-key"] == "engine-key"
    assert seen["headers"]["x-q99-agent"] == "report.chat"


async def test_an_engine_agent_client_sends_only_the_engine_key_and_the_agent():
    sdk = UserManagerSDK(api_key="engine-key").as_agent("report.consistency-reviewer")
    seen = capture(sdk)

    await sdk.create_report_comments_batch("r1", [{"body": "x"}], supersede=True)

    assert seen["headers"]["authorization"] == "Api-Key engine-key"
    assert "x-engine-key" not in seen["headers"]
    assert seen["headers"]["x-q99-agent"] == "report.consistency-reviewer"


def test_as_agent_leaves_the_original_client_as_it_was():
    sdk = UserManagerSDK("user-jwt")

    sdk.as_agent("report.chat", engine_key="k")

    assert sdk.agent is None and sdk.engine_key is None
