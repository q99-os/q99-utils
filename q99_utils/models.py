from enum import StrEnum
from typing import Any, Dict, Literal, Optional

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
    webpages = "webpages"
    slack = "slack"
    greenapi = "greenapi"
    greenapi_partner = "greenapi-partner"
    openwells = "openwells"
    gmail = "gmail",
    outlook = "outlook"


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

class OnboardingData(BaseModel):
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
    root_folder: str | None = Field(default=None)
    instance_id: str | None = Field(default=None)
    partner_token: str | None = Field(default=None)
    instance_name: str | None = Field(default=None)
    database_backend: DatabaseBackendEnum | None = Field(default=None)


class UMMessage(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = {}
    type: Literal["Question", "Answer", "Interruption", "Error"]

