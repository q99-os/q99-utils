from q99_utils.models import UMMessage
from q99_utils.um_sdk import UserManagerSDK


async def test_add_interaction_propagates_graph_context(monkeypatch):
    captured = {}

    async def request(**kwargs):
        captured.update(kwargs)
        return {"id": "interaction", "conversation_id": "conversation"}

    sdk = UserManagerSDK(access_token="test-token")
    monkeypatch.setattr(sdk, "_request", request)
    try:
        await sdk.add_interaction(
            message=UMMessage(type="Question", content="hello"),
            graph_id="11111111-1111-4111-8111-111111111111",
        )
    finally:
        await sdk._client.aclose()

    assert captured["json"]["graph_id"] == "11111111-1111-4111-8111-111111111111"
