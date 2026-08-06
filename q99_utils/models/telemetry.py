from typing import Literal, Optional

from pydantic import BaseModel

TraceType = Literal["chat", "embedding", "vision", "stt"]
TraceGroupStatus = Literal["running", "completed", "error", "stopped"]


class UMTrace(BaseModel):
    id: Optional[str] = None
    created_at: Optional[int] = None  # epoch seconds; UM defaults to now() if omitted
    type: TraceType
    provider: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    cost: Optional[float] = None
    duration: Optional[float] = None
    user: Optional[int] = None  # User PK (Django int)
    agent_name: Optional[str] = None
    trace_group_id: Optional[str] = None
    finish_reason: Optional[str] = None
    error: Optional[str] = None


class UMTraceGroup(BaseModel):
    id: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    conversation_id: Optional[str] = None
    user: Optional[int] = None
    status: Optional[TraceGroupStatus] = None
    total_traces: Optional[int] = None
    total_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_cost: Optional[float] = None
    total_duration: Optional[float] = None
    error_count: Optional[int] = None


__all__ = ["TraceGroupStatus", "TraceType", "UMTrace", "UMTraceGroup"]
