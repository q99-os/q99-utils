"""What the host hands every integration: config plus its port adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from q99_utils.integrations.ports import (
    ConnectionRegistry,
    FileReferenceStore,
    InMemoryConnectionRegistry,
    ManagedBucketProvider,
    SqlDriverFactory,
    StorageServiceFactory,
)


class IntegrationConfig(BaseModel):
    """Deployment settings the integrations read.

    Only the keys actually consumed here; the host maps its own settings in.
    """

    environment: str = Field(
        default="local",
        description="Deployment environment; some providers expose different endpoints outside prod.",
    )
    webhook_base_url: Optional[str] = Field(
        default=None,
        description="Public base URL the host is reachable at, used to register provider webhooks.",
    )
    upload_max_size_mb: int = Field(
        default=200,
        description="Files larger than this are skipped during discovery.",
    )
    cloud_provider: str = Field(
        default="aws",
        description="Deployment's default cloud provider, used when the source doesn't imply one.",
    )
    object_storage_name: str = Field(
        default="",
        description="Deployment's default bucket name.",
    )
    managed_bucket_source: str = Field(
        default="quantos_bucket",
        description="Sentinel source value identifying the host's own bucket credential.",
    )


@dataclass(slots=True)
class IntegrationContext:
    """Host-supplied collaborators.

    Everything has a working default, so an integration that needs none of them
    can be built with just source + um_sdk.
    """

    config: IntegrationConfig = field(default_factory=IntegrationConfig)
    connections: ConnectionRegistry = field(default_factory=InMemoryConnectionRegistry)
    driver_factory: Optional[SqlDriverFactory] = None
    file_store: Optional[FileReferenceStore] = None
    storage_factory: Optional[StorageServiceFactory] = None
    managed_bucket: Optional[ManagedBucketProvider] = None


__all__ = ["IntegrationConfig", "IntegrationContext"]
