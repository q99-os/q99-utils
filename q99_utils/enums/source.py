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
    alamo = "alamo"
    # Login-only sources, kept separate from azure_ad (which owns IdP group sync)
    # so an SSO credential and a group-sync credential never share a source.
    microsoft_sso = "microsoft_sso"
    google_sso = "google_sso"
    google_oauth_app = "google_oauth_app"
    microsoft_oauth_app = "microsoft_oauth_app"


__all__ = ["SourceEnum"]
