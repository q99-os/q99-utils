"""Contract every source integration implements."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from q99_utils.integrations.core.context import IntegrationContext
from q99_utils.integrations.discovery import DiscoveredFile, ResourceNode
from q99_utils.models import PermissionTokens
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData
from q99_utils.um_sdk import UserManagerSDK


class SourceIntegrationInterface:
    def __init__(
        self,
        source: SourceEnum,
        um_sdk: UserManagerSDK,
        context: Optional[IntegrationContext] = None,
    ) -> None:
        self.um_sdk = um_sdk
        self.source = source
        self.context = context or IntegrationContext()
        self.credential_id: Optional[str] = None
        self.root_paths_override: Optional[List[str]] = None
        self.credentials: Optional[Dict[str, Any]] = None

    @property
    def config(self):
        return self.context.config

    async def get_credentials(self) -> OnboardingData:
        if not self.credential_id:
            raise ValueError(
                f"credential_id must be set before get_credentials() (source '{self.source}')"
            )
        credential = await self.um_sdk.get_credential(credential_id=self.credential_id)
        self.credentials = credential
        creds = OnboardingData(**credential)
        if self.root_paths_override:
            creds.root_folders = self.root_paths_override
        return creds

    async def persist_tokens(self, credentials: OnboardingData) -> None:
        """Store a refreshed token, so a rotated one does not leave the saved one dead."""
        if not self.credential_id:
            return

        await self.um_sdk.update_credentials(
            data=OnboardingData(
                source=credentials.source,
                integration_type=credentials.integration_type,
                api_key=credentials.api_key,
                refresh_token=credentials.refresh_token,
            ),
            credential_id=self.credential_id,
        )

    async def list_tree(self, path: str = "") -> Tuple[List[ResourceNode], bool]:
        return [], False

    @classmethod
    def _extract_permissions(cls, file_metadata: Any) -> List[str]:
        """Extract ACL permission tokens from source-specific file metadata.

        This is the extension point for integrations with native ACL APIs
        (e.g. Google Drive, SharePoint). Override it to return tokens derived
        from the provider's permission objects.

        The base implementation grants admin-only access — the correct default
        for sources without per-file ACLs (S3, local files, databases, etc.).
        Admins can re-grant broader access manually.

        Not strictly substitutable: SharePoint's override also takes a resolved
        group-name map, so callers hold a concrete class, not this interface.
        """
        return [PermissionTokens.ADMIN_ONLY]

    async def files_discovery(self) -> Tuple[List[DiscoveredFile], Optional[dict]]:
        """Discover files for this credential.

        Returns ``(files, sync_cursors)``. The cursor slot carries the
        provider's incremental state for :meth:`save_sync_state`, or None for
        sources that have none.
        """
        raise NotImplementedError

    async def get_files_from_path(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs,
    ):
        raise NotImplementedError

    async def _roots_needing_full_scan(self, roots: Sequence[str]) -> List[str]:
        """Roots with zero indexed files — those need a full scan, not a delta.

        Without a file store, or before a credential is known, every root
        counts as new.
        """
        store = self.context.file_store
        if not (self.credential_id and store):
            return list(roots)

        needing = []
        for root in roots:
            indexed = await store.has_indexed_files(
                credential_id=self.credential_id,
                source=str(self.source),
                reference_patterns=[f"{root}/%" if root else "%"],
            )
            if not indexed:
                needing.append(root)
        return needing

    async def dialect(self) -> str:
        """Return the canonical sqlglot SQL dialect for this integration's backend.

        Used downstream by StructuredDataQueryTool and DBSchemaExplorerTool to drive
        Text2SQLAgent and validate_sql with the correct dialect. The returned string
        must be one sqlglot accepts (postgres, tsql, bigquery, databricks).
        """
        raise NotImplementedError

    async def load_sync_cursors(self) -> dict:
        """Read this credential's sync_cursors dict from UM. Returns {} on first
        sync (no cursors stored yet) or when credential_id isn't set.
        sync_cursors stores provider-specific incremental-discovery cursors
        (Graph delta links, GDrive page tokens, etc.)."""
        if not self.credential_id:
            return {}
        credential = await self.um_sdk.get_credential(credential_id=self.credential_id)
        return dict(credential.get("sync_cursors") or {})

    async def save_sync_state(self, sync_cursors: dict) -> None:
        """PATCH this credential's sync_cursors and stamp last_sync to now.
        Call once at the END of a successful discovery run — if discovery
        throws, the prior cursors stay in UM and the next run resumes from
        the last successful checkpoint."""
        if not self.credential_id:
            return
        await self.um_sdk.update_sync_state(
            credential_id=self.credential_id,
            sync_cursors=sync_cursors,
            last_sync=datetime.now(timezone.utc).isoformat(),
        )


__all__ = ["SourceIntegrationInterface"]
