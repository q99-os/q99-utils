"""Concrete source integrations.

These imports populate the registry: ``@register`` runs at import time, so
anything missing here is invisible to ``create_integration``.
"""

from q99_utils.integrations.sources.alamo import AlamoIntegration
from q99_utils.integrations.sources.azure_ad import AzureADIntegration
from q99_utils.integrations.sources.bigquery import BigQueryIntegration
from q99_utils.integrations.sources.bucket import BucketIntegration
from q99_utils.integrations.sources.databricks import DatabricksIntegration
from q99_utils.integrations.sources.google_sso import GoogleSsoIntegration
from q99_utils.integrations.sources.greenapi import GreenAPIIntegration
from q99_utils.integrations.sources.local_files import LocalFilesIntegration
from q99_utils.integrations.sources.mssql import MSSQLIntegration
from q99_utils.integrations.sources.postgres import PostgresIntegration
from q99_utils.integrations.sources.slack import SlackIntegration

__all__ = [
    "AlamoIntegration",
    "AzureADIntegration",
    "BigQueryIntegration",
    "BucketIntegration",
    "DatabricksIntegration",
    "GoogleSsoIntegration",
    "GreenAPIIntegration",
    "LocalFilesIntegration",
    "MSSQLIntegration",
    "PostgresIntegration",
    "SlackIntegration",
]
