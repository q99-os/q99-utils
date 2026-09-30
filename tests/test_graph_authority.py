from datetime import UTC, datetime

import pytest

from q99_utils.models import (
    GraphAccessDecision,
    GraphAuthorityDecision,
    GraphAuthorityReference,
    GraphOperation,
)
from q99_utils.um_sdk import UserManagerSDK


GRAPH_ID = "11111111-1111-4111-8111-111111111111"
DECISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REFERENCE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


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
    second_graph_id = "22222222-2222-4222-8222-222222222222"
    calls = []

    async def request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            return {
                "next": None,
                "results": [{
                    "id": second_graph_id,
                    "name": "Secondary",
                    "description": "",
                    "is_active": True,
                    "policy_version": 2,
                }],
            }
        return {
            "next": "/v1/graphs/?operation=read&page=2",
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
    assert [str(graph.id) for graph in graphs] == [GRAPH_ID, second_graph_id]
    assert calls[0]["params"] == {"operation": "read"}
    assert calls[1]["params"] is None
    await sdk._client.aclose()


async def test_list_graphs_rejects_cycles_and_silent_truncation(monkeypatch):
    sdk = UserManagerSDK(api_key="key")

    async def cycling_request(**_kwargs):
        return {
            "next": "/v1/graphs/",
            "results": [],
        }

    monkeypatch.setattr(sdk, "_request", cycling_request)
    with pytest.raises(ValueError, match="pagination cycled"):
        await sdk.list_graphs("materialize")

    async def oversized_request(**_kwargs):
        return {
            "next": None,
            "results": [
                {
                    "id": GRAPH_ID,
                    "name": "Primary",
                    "description": "",
                    "is_active": True,
                    "policy_version": 1,
                },
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "name": "Secondary",
                    "description": "",
                    "is_active": True,
                    "policy_version": 1,
                },
            ],
        }

    monkeypatch.setattr(sdk, "_request", oversized_request)
    with pytest.raises(ValueError, match="exceeded graph limit"):
        await sdk.list_graphs("read", max_graphs=1)
    await sdk._client.aclose()


async def test_list_graphs_rejects_cross_origin_next_link(monkeypatch):
    sdk = UserManagerSDK(api_key="key")

    async def request(**_kwargs):
        return {
            "next": "https://attacker.invalid/v1/graphs/?page=2",
            "results": [],
        }

    monkeypatch.setattr(sdk, "_request", request)
    with pytest.raises(ValueError, match="changed origin"):
        await sdk.list_graphs("read")
    await sdk._client.aclose()


async def test_authority_reference_lifecycle_uses_opaque_handle(monkeypatch):
    sdk = UserManagerSDK(access_token="token")
    calls = []
    base = {
        "id": REFERENCE_ID,
        "graph_id": GRAPH_ID,
        "actor_kind": "user",
        "actor_id": "user-1",
        "actor_operation": "ingest",
        "operation": "materialize",
        "executor_service": "graph-neuro-scheduler",
        "expires_at": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
    }

    async def request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "DELETE":
            return None
        if kwargs["url"].endswith("/resolve/"):
            return {**base, "policy_version": 8}
        return {
            **base,
            "revoked_at": None,
            "created_at": datetime(2029, 1, 1, tzinfo=UTC).isoformat(),
        }

    monkeypatch.setattr(sdk, "_request", request)
    reference = await sdk.create_graph_authority_reference(
        GRAPH_ID,
        actor_operation="ingest",
        operation=GraphOperation.MATERIALIZE,
        executor_service="graph-neuro-scheduler",
        ttl_seconds=600,
    )
    decision = await sdk.resolve_graph_authority_reference(str(reference.id))
    await sdk.revoke_graph_authority_reference(str(reference.id))

    assert isinstance(reference, GraphAuthorityReference)
    assert isinstance(decision, GraphAuthorityDecision)
    assert calls[0]["json"]["actor_operation"] == "ingest"
    assert calls[1]["method"] == "POST"
    assert calls[2]["method"] == "DELETE"
    await sdk._client.aclose()
