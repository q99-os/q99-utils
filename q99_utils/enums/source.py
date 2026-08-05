from enum import StrEnum


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


__all__ = ["SourceEnum"]
