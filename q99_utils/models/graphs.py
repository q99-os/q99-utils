"""Typed contracts for knowledge-graph catalog authorization."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GraphOperation(StrEnum):
    READ = "read"
    INGEST = "ingest"
    REVIEW = "review"
    MATERIALIZE = "materialize"
    ADMIN = "admin"


class UMKnowledgeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str = ""
    is_active: bool
    policy_version: int


class GraphAccessDecision(UMKnowledgeGraph):
    operation: GraphOperation
    allowed: bool
    actor_id: str
    actor_kind: str
    decision_id: UUID
    expires_at: datetime | None = None


class GraphAuthorityReference(BaseModel):
    """Opaque, revocable authority handle for asynchronous graph work."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    graph_id: UUID
    actor_kind: str
    actor_id: str
    actor_operation: GraphOperation
    operation: GraphOperation
    executor_service: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime


class GraphAuthorityDecision(BaseModel):
    """Current authority reconstructed by User Manager for an executor."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    graph_id: UUID
    actor_kind: str
    actor_id: str
    actor_operation: GraphOperation
    operation: GraphOperation
    executor_service: str
    policy_version: int
    expires_at: datetime
