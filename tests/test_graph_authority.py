from datetime import UTC, datetime

import pytest

from q99_utils.models import GraphAccessDecision, GraphOperation
from q99_utils.um_sdk import UserManagerSDK


GRAPH_ID = "11111111-1111-4111-8111-111111111111"
DECISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


async def test_authorize_graph_posts_operation_and_validates_response(monkeypatch):
    sdk = UserManagerSDK(access_token="token")
    calls = []

    async def request(**kwargs):
        calls.append(kwargs)
        return {
            "id": GRAPH_ID,
            "name": "Primary",
            "description": "",
            "is_active": True,
            "policy_version": 7,
            "operation": "ingest",
            "allowed": True,
            "actor_id": "user-1",
            "actor_kind": "user",
            "decision_id": DECISION_ID,
            "expires_at": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
        }

    monkeypatch.setattr(sdk, "_request", request)
    decision = await sdk.authorize_graph(GRAPH_ID, GraphOperation.INGEST)

    assert isinstance(decision, GraphAccessDecision)
    assert decision.operation is GraphOperation.INGEST
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {"operation": "ingest"}
    await sdk._client.aclose()


async def test_authorize_graph_rejects_unknown_operation():
    sdk = UserManagerSDK(access_token="token")
    with pytest.raises(ValueError):
        await sdk.authorize_graph(GRAPH_ID, "write")
    await sdk._client.aclose()


async def test_list_graphs_accepts_paginated_catalog(monkeypatch):
    sdk = UserManagerSDK(api_key="key")

    async def request(**_kwargs):
        return {
            "results": [{
                "id": GRAPH_ID,
                "name": "Primary",
                "description": "",
                "is_active": True,
                "policy_version": 1,
            }]
        }

    monkeypatch.setattr(sdk, "_request", request)
    graphs = await sdk.list_graphs("read")
    assert [str(graph.id) for graph in graphs] == [GRAPH_ID]
    await sdk._client.aclose()
