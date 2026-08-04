"""Ports for object storage.

The real S3/Blob/GCS clients live in the host's cloud-services library; these
protocols keep that private git dependency out of q99-utils.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Protocol, Sequence, Set, Tuple, runtime_checkable


@runtime_checkable
class StorageService(Protocol):
    """A provider-specific storage client, built by the host.

    Objects from ``files_discovery`` must expose ``path``, ``file_size``,
    ``source_modified_at``, ``content_hash`` and ``mime_type``.
    """

    def download_bites_file(self, container: str, key: str) -> Any:
        ...

    async def files_discovery(
        self,
        container: str,
        ingested_paths: Set[str],
        latest_modified_at: int,
        max_file_size_mb: int = ...,
        prefix: str = ...,
    ) -> List[Any]:
        ...

    def list_tree(self, container: str, prefixes: Sequence[str], depth: int) -> Tuple[List[Any], bool]:
        ...


@runtime_checkable
class StorageServiceFactory(Protocol):
    """Builds a :class:`StorageService` for a cloud provider.

    No credentials means "use the deployment's ambient ones".
    """

    def get(self, provider: str, **credentials: Any) -> StorageService:
        ...


class ManagedBucket(NamedTuple):
    """The host's own object-storage bucket, resolved at runtime."""

    cloud_provider: str
    bucket_name: str
    storage_creds: Dict[str, Any]


@runtime_checkable
class ManagedBucketProvider(Protocol):
    """Resolves the host's own bucket credential.

    Provisioned by the platform rather than by a user, and cached by the host,
    so it doesn't come from the User Manager.
    """

    async def managed_bucket(self) -> Optional[ManagedBucket]:
        ...


__all__ = [
    "StorageService",
    "StorageServiceFactory",
    "ManagedBucket",
    "ManagedBucketProvider",
]
