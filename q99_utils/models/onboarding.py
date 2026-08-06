from pydantic import BaseModel, Field

from q99_utils.enums import DatabaseBackendEnum, IntegrationTypeEnum, SourceEnum


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


__all__ = ["OnboardingData"]
