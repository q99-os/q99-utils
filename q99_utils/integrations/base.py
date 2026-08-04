"""Contract every source integration implements.

Subclasses override only what their provider supports; the defaults here are
the safe behaviour for the ones that don't.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from q99_utils.integrations.context import IntegrationContext
from q99_utils.integrations.models import PermissionTokens, ResourceNode
from q99_utils.models import OnboardingData, SourceEnum
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
        # Set by the ingestion pipeline when a specific credential is known
        # (from files_references.credential_id) — allows multi-credential disambiguation.
        self.credential_id: Optional[str] = None
        # When set by DiscoveryService, overrides credentials.root_folders so
        # files_discovery() walks these paths instead of the ones stored in UM.
        self.root_paths_override: Optional[List[str]] = None

    @property
    def config(self):
        """Shorthand for ``self.context.config``."""
        return self.context.config

    async def get_credentials(self) -> OnboardingData:
        if not self.credential_id:
            raise ValueError(
                f"credential_id must be set before get_credentials() (source '{self.source}')"
            )
        # Direct lookup by ID — works regardless of active/inactive status
        # and avoids filtering ambiguity for multi-credential sources.
        credential = await self.um_sdk.get_credential(credential_id=self.credential_id)
        self.credentials = credential
        creds = OnboardingData(**credential)
        # Allow the discovery service to scope a walk to specific paths
        # without modifying the stored credential.
        if self.root_paths_override:
            creds.root_folders = self.root_paths_override
        return creds

    async def list_tree(self, path: str = "") -> Tuple[List[ResourceNode], bool]:
        """List immediate folder children of *path* (empty = source root). Base returns none."""
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
        """
        return [PermissionTokens.ADMIN_ONLY]

    async def resolve_permissions(self, requested: List[str] | None = None) -> List[str]:
        """Determine effective permissions for discovered file references.

        Each integration decides how permissions are assigned:
          - local_files: honours caller-supplied folder roles.
          - drive: reads Google ACLs via _extract_permissions.
          - sharepoint: reads Graph API ACLs via _extract_permissions.

        The base implementation ignores the request and returns [ADMIN_ONLY].
        Subclasses override this to implement source-specific logic.
        """
        return [PermissionTokens.ADMIN_ONLY]

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
