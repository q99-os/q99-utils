from __future__ import annotations

import asyncio
import mimetypes
import os
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from q99_utils.integrations.core import IntegrationContext, SourceIntegrationInterface, register
from q99_utils.integrations.discovery import DiscoveredFile, ResourceNode

from q99_utils.integrations.ports import StorageService
from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.um_sdk import UserManagerSDK

logger = get_logger(__name__)

PROVIDER_BY_BUCKET_SOURCE = {
    str(SourceEnum.s3): "aws",
    str(SourceEnum.blob): "azure",
    str(SourceEnum.gcs): "gcp",
}

AWS = "aws"
AZURE = "azure"
GCP = "gcp"


@register(SourceEnum.s3, SourceEnum.blob, SourceEnum.gcs)
class BucketIntegration(SourceIntegrationInterface):
    """Cloud-agnostic bucket integration.

    Resolves which cloud provider to use via:
    1. The *source* value itself  (s3 → aws, blob → azure, gcs → gcp).
    2. The URI scheme stored in `reference`  (s3://… → aws, azure://… → azure, gcs://… → gcp).
    3. Deployment defaults (``config.cloud_provider`` / ``config.object_storage_name``).

    For **manual_uploads** the host's own bucket credential is resolved through
    the ManagedBucketProvider port (the platform provisions and caches it).

    For **externally-onboarded buckets** (source = s3 / blob / gcs) the onboarding
    stores the target bucket name in `OnboardingData.url` and optional
    prefixes in `OnboardingData.root_folders`.  At runtime those are loaded
    via `_load_external_config()`.
    """

    def __init__(
        self,
        source,
        um_sdk: UserManagerSDK,
        context: Optional[IntegrationContext] = None,
    ) -> None:
        super().__init__(source=source, um_sdk=um_sdk, context=context)
        self.cloud_provider: str = PROVIDER_BY_BUCKET_SOURCE.get(
            str(source), str(self.config.cloud_provider)
        )
        self.bucket_name: str = self.config.object_storage_name
        self.prefixes: List[str] = []
        self._external_loaded: bool = False
        self._external_creds: dict = {}

    # Credential helpers

    async def get_access_token(self):
        ...

    def _storage(self, provider: str, with_credentials: bool = True) -> StorageService:
        factory = self.context.storage_factory
        if factory is None:
            raise RuntimeError(
                "No storage_factory configured on the IntegrationContext — "
                f"'{self.source}' cannot reach object storage."
            )
        return factory.get(provider, **(self._external_creds if with_credentials else {}))

    async def _load_external_config(self):
        """Load bucket_name / prefixes / credentials from stored credentials.

        For manual_uploads: resolves the host's own bucket credential.
        For external buckets (s3/blob/gcs): fetches stored onboarding credentials.
        """
        if self._external_loaded:
            return
        self._external_loaded = True

        try:
            if str(self.source) == str(self.config.managed_bucket_source):
                provider = self.context.managed_bucket
                cached = await provider.managed_bucket() if provider else None
                if cached:
                    self.cloud_provider = cached.cloud_provider
                    self.bucket_name = cached.bucket_name
                    self._external_creds = dict(cached.storage_creds)
                else:
                    logger.debug("[BucketIntegration] No cached managed bucket.")
            else:
                creds = await super().get_credentials()
                if getattr(creds, "url", None):
                    self.bucket_name = str(creds.url)
                self._extract_provider_creds_from_onboarding(creds)
        except Exception as e:
            logger.debug(f"[BucketIntegration] No external credentials for source={self.source}: {e}")

    def _extract_provider_creds_from_onboarding(self, creds):
        if self.cloud_provider == AWS:
            if getattr(creds, "api_key", None):
                self._external_creds["aws_key"] = creds.api_key
            if getattr(creds, "client_secret", None):
                self._external_creds["aws_secret"] = creds.client_secret
        elif self.cloud_provider == AZURE:
            if getattr(creds, "api_key", None):
                self._external_creds["connection_string"] = creds.api_key
        elif self.cloud_provider == GCP:
            if getattr(creds, "api_key", None):
                self._external_creds["service_account_json"] = creds.api_key

    # Reference URI helpers

    @staticmethod
    def _split_reference(file_path: str) -> Tuple[Optional[str], Optional[str], str]:
        """Split `scheme://container/key` into (scheme, container, key).

        Plain paths (no scheme) return (None, None, file_path).
        """
        if "://" not in file_path:
            return None, None, file_path
        try:
            scheme, rest = file_path.split("://", 1)
            container, key = rest.split("/", 1)
            return scheme, container, key
        except ValueError:
            return None, None, file_path

    @staticmethod
    def _provider_from_scheme(scheme: Optional[str]) -> Optional[str]:
        if not scheme:
            return None
        return PROVIDER_BY_BUCKET_SOURCE.get(scheme.lower())

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        return (prefix or "").strip().strip("/")

    @staticmethod
    def _reference_patterns(resolved_prefix: str) -> Optional[List[str]]:
        if not resolved_prefix:
            return None
        return [resolved_prefix, f"{resolved_prefix}/%"]

    # File download (used during ingestion pipeline)

    async def get_files_from_path(
        self,
        file_path: str,
        metadata: Dict[str, Any] = None,
        config: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs,
    ):
        await self._load_external_config()

        config = config or {}
        source_scheme, source_bucket, source_key = self._split_reference(file_path)
        scheme_provider = self._provider_from_scheme(source_scheme)
        cloud_provider = str(config.get("cloud_provider", scheme_provider or self.cloud_provider))
        bucket_name = config.get("bucket_name") or source_bucket or self.bucket_name

        cloud_storage = self._storage(
            cloud_provider, with_credentials=cloud_provider == self.cloud_provider
        )
        try:
            downloaded_file = cloud_storage.download_bites_file(container=bucket_name, key=source_key)
            return BytesIO(downloaded_file.read())
        except Exception:
            logger.warning(
                f"[BucketIntegration] Failed to fetch — provider={cloud_provider}, "
                f"bucket={bucket_name}, key={source_key}",
                exc_info=True,
            )
            return None

    # File discovery (used during onboarding)

    async def files_discovery(
        self,
        bucket_name: Optional[str] = None,
        prefix: str = "",
    ) -> Tuple[List[DiscoveredFile], None]:

        await self._load_external_config()
        store = self.context.file_store

        if self.credential_id and store:
            ingested_paths = await store.known_references(
                credential_id=self.credential_id,
                source=str(self.source),
            )
        else:
            ingested_paths = set()

        resolved_bucket = bucket_name or self.bucket_name

        if prefix:
            prefixes_to_scan = [prefix]
        else:
            creds = await self.get_credentials()
            configured_prefixes = creds.root_folders or []
            prefixes_to_scan = configured_prefixes if configured_prefixes else [""]

        all_discovered: List[DiscoveredFile] = []
        cloud_storage = self._storage(self.cloud_provider)

        for scan_prefix in prefixes_to_scan:
            resolved_prefix = self._normalize_prefix(scan_prefix)

            if self.credential_id and store:
                latest_modified_at = await store.latest_source_modified_at(
                    credential_id=self.credential_id,
                    source=str(self.source),
                    reference_patterns=self._reference_patterns(resolved_prefix),
                )
            else:
                latest_modified_at = 0

            try:
                discovered_objects = await cloud_storage.files_discovery(
                    resolved_bucket,
                    ingested_paths,
                    latest_modified_at,
                    max_file_size_mb=self.config.upload_max_size_mb,
                    prefix=resolved_prefix,
                )
            except NotImplementedError:
                logger.warning(
                    f"[BucketIntegration] files_discovery not supported by provider={self.cloud_provider}. Returning empty."
                )
                continue

            all_discovered.extend(
                DiscoveredFile(
                    name=os.path.basename(obj.path),
                    reference=obj.path,
                    file_size=obj.file_size,
                    source_modified_at=obj.source_modified_at,
                    content_hash=obj.content_hash,
                    mime_type=obj.mime_type or mimetypes.guess_type(obj.path)[0],
                )
                for obj in discovered_objects
            )

        return all_discovered, None

    async def list_tree(self, path: str = "") -> Tuple[List[ResourceNode], bool]:
        await self._load_external_config()

        cloud_storage = self._storage(self.cloud_provider)

        creds = await self.get_credentials()
        configured_prefixes = creds.root_folders or []

        if path:
            start_prefixes = [path]
        elif configured_prefixes:
            start_prefixes = configured_prefixes
        else:
            start_prefixes = [""]

        prefixes = [self._normalize_prefix(p) for p in start_prefixes]
        folder_nodes, _ = await asyncio.to_thread(
            cloud_storage.list_tree, self.bucket_name, prefixes, 1,
        )

        def to_resource_nodes(nodes):
            return [
                ResourceNode(
                    name=fn.name,
                    path=f"{self.cloud_provider}://{self.bucket_name}/{fn.path}",
                    node_type="folder",
                    has_children=fn.has_children,
                    file_count=fn.file_count,
                    children=to_resource_nodes(fn.children),
                )
                for fn in nodes
            ]

        return to_resource_nodes(folder_nodes), False


__all__ = ["BucketIntegration", "PROVIDER_BY_BUCKET_SOURCE"]
