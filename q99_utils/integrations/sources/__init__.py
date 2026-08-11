"""Concrete source integrations. These imports are what populate the registry."""

from q99_utils.logger import get_logger

from q99_utils.integrations.sources.azure_ad import AzureADIntegration
from q99_utils.integrations.sources.bigquery import BigQueryIntegration
from q99_utils.integrations.sources.bucket import BucketIntegration
from q99_utils.integrations.sources.databricks import DatabricksIntegration
from q99_utils.integrations.sources.gmail import GmailIntegration
from q99_utils.integrations.sources.greenapi import GreenAPIIntegration
from q99_utils.integrations.sources.local_files import LocalFilesIntegration
from q99_utils.integrations.sources.mssql import MSSQLIntegration
from q99_utils.integrations.sources.openwells import OpenWellsIntegration
from q99_utils.integrations.sources.outlook import OutlookIntegration
from q99_utils.integrations.sources.postgres import PostgresIntegration
from q99_utils.integrations.sources.sharepoint import SharepointIntegration
from q99_utils.integrations.sources.slack import SlackIntegration

# Narrow on purpose: only a missing SDK is an absent extra, anything else is a bug.
try:
    from q99_utils.integrations.sources.google_drive import GoogleDriveIntegration
except ImportError as exc:  # pragma: no cover - depends on install extras
    if (exc.name or "").split(".")[0] not in {"google", "googleapiclient"}:
        raise
    GoogleDriveIntegration = None
    get_logger(__name__).warning(
        "Google Drive integration unavailable: install q99-utils[google]."
    )

__all__ = [
    "AzureADIntegration",
    "BigQueryIntegration",
    "BucketIntegration",
    "DatabricksIntegration",
    "GmailIntegration",
    "GoogleDriveIntegration",
    "GreenAPIIntegration",
    "LocalFilesIntegration",
    "MSSQLIntegration",
    "OpenWellsIntegration",
    "OutlookIntegration",
    "PostgresIntegration",
    "SharepointIntegration",
    "SlackIntegration",
]

if GoogleDriveIntegration is None:
    # Bound to None it would fail at call time; absent, the import fails where written.
    __all__.remove("GoogleDriveIntegration")
