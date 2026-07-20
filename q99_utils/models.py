from enum import StrEnum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

class SourceEnum(StrEnum):
    local_files = "local_files"
    sharepoint = "sharepoint"
    googledrive = "googledrive"
    databricks = "databricks"
    openai = "openai"
    postgres = "postgresql"
    mssql = "mssql"
    anthropic = "anthropic"
    gemini = "gemini"
    azure = "azure"
    s3 = "s3"
    blob = "blob"
    gcs = "gcs"
    webpages = "webpages"
    slack = "slack"
    greenapi = "greenapi"
    greenapi_partner = "greenapi-partner"
    openwells = "openwells"
    gmail = "gmail"
    outlook = "outlook"
    azure_ad = "azure_ad"
    bigquery = "bigquery"


class DatabaseBackendEnum(StrEnum):
    postgres = "postgresql"
    mssql = "mssql"


class IntegrationTypeEnum(StrEnum):
    file_system = "file_system"
    database = "database"
    chat_model = "chat_model"
    embeddings_model = "embeddings_model"
    reasoning_model = "reasoning_model"
    bot = "bot"
    email = "email"
    idp = "idp"

class OnboardingData(BaseModel):
    id: str | None = Field(default=None)
    source: SourceEnum = Field(...)
    integration_type: IntegrationTypeEnum = Field(default=None)

    api_key: str | None = Field(default=None)
    api_version: str | None = Field(default=None)
    api_base: str | None = Field(default=None)
    client_id: str | None = Field(default=None)
    tenant_id: str | None = Field(default=None)
    client_secret: str | None = Field(default=None)
    tenant_name: str | None = Field(default=None)
    site_name: str | None = Field(default=None)
    site_id: str | None = Field(default=None)
    refresh_token: str | None = Field(default=None)
    token_expiry: str | None = Field(default=None)
    workspace: str | None = Field(default=None)
    url: str | None = Field(default=None)
    username: str | None = Field(default=None)
    password: str | None = Field(default=None)
    database_name: str | None = Field(default=None)
    host: str | None = Field(default=None)
    port: str | None = Field(default=None)
    root_folders: list[str] | None = Field(default=None)
    instance_id: str | None = Field(default=None)
    partner_token: str | None = Field(default=None)
    instance_name: str | None = Field(default=None)
    database_backend: DatabaseBackendEnum | None = Field(default=None)


class UMMessage(BaseModel):
    content: str = ""
    steps: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = {}
    type: Literal["Question", "Answer", "Interruption", "Error"]


# === Telemetry ===

TraceType = Literal["chat", "embedding", "vision", "stt"]
TraceGroupStatus = Literal["running", "completed", "error", "stopped"]


class UMTrace(BaseModel):
    """A single LLM/embedding/vision/stt call record."""
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
    """Pre-aggregated stats for one agent invocation / conversation turn."""
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


# === Exports ===

class UMExport(BaseModel):
    """File export record (chat report, extraction, query result, etc.)."""
    id: Optional[str] = None
    created_at: Optional[int] = None
    user: Optional[int] = None
    filename: str
    mime_type: str
    storage_path: str
    size_bytes: Optional[int] = None
    source_type: Optional[str] = None  # e.g., "chat_report", "extraction", "query"
    source_id: Optional[str] = None


# === Reports ===

class UMReportSection(BaseModel):
    """One section of a generated report — the mutable working copy lives in UM."""
    name: str
    section_order: int
    content: dict = {}


class UMReport(BaseModel):
    """Report creation payload (report + full section skeleton, atomic).
    Author is resolved by UM from the caller's token."""
    report_type: str
    title: str
    metadata: dict
    sections: list[UMReportSection]


# === Task Scheduling ===

class UMCrontab(BaseModel):
    """Cron schedule. Each field accepts standard cron syntax ('*', '0', '*/15', '1,3,5', etc.)."""
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"


class UMTaskSchedule(BaseModel):
    """Request body for creating a scheduled task. `task_definition` is the
    registered task name (slug, e.g. 'run_file_discovery'); see UM's
    TASK_REGISTRY for what's available."""
    task_definition: str
    crontab: UMCrontab
    enabled: bool = True

