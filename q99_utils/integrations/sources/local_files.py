"""Local filesystem integration."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from q99_utils.integrations.base import SourceIntegrationInterface
from q99_utils.integrations.models import DiscoveredFile, ResourceNode
from q99_utils.integrations.registry import register
from q99_utils.logger import get_logger
from q99_utils.models import OnboardingData, SourceEnum

logger = get_logger(__name__)


@register(SourceEnum.local_files)
class LocalFilesIntegration(SourceIntegrationInterface):

    async def get_files_from_path(
        self,
        file_path: str,
        metadata: Dict[str, Any] = None,
        config: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs,
    ):
        metadata = metadata or {}
        config = config or {}
        base_path = config.get("path", "")
        resolved_path = Path(base_path) / file_path
        resolved_path = resolved_path.resolve()

        if not resolved_path.exists():
            logger.warning(f"File not found: {resolved_path}")
            return None
        if not resolved_path.is_file():
            logger.warning(f"Path exists but is not a file: {resolved_path}")
            return None
        try:
            def _sync_read():
                with open(resolved_path, "rb") as f:
                    return io.BytesIO(f.read())
            return await asyncio.to_thread(_sync_read)
        except Exception:
            logger.exception(f"Failed to read file at {resolved_path}")
            return None

    async def get_access_token(self):
        ...

    async def files_discovery(self) -> Tuple[List[DiscoveredFile], None]:

        credentials: OnboardingData = await self.get_credentials()
        max_file_size_mb: int = self.config.upload_max_size_mb
        store = self.context.file_store

        root_folders = credentials.root_folders or []
        d_files = []

        for root_folder in root_folders:
            root_prefix = os.path.normpath(root_folder)
            if root_prefix and not root_prefix.endswith(os.sep):
                root_prefix = f"{root_prefix}{os.sep}"

            # References are stored with the OS separator.
            patterns = [f"{root_prefix}%"] if root_prefix else None

            if self.credential_id and store:
                refs = await store.known_references(
                    credential_id=self.credential_id,
                    reference_patterns=patterns,
                )
                ingested_paths = set(os.path.normpath(r) for r in refs)
            else:
                ingested_paths = set()

            if self.credential_id and root_prefix and store:
                # No trustworthy provider timestamp here, so compare against
                # when we last ingested.
                latest_created_at = await store.latest_ingested_at(
                    credential_id=self.credential_id,
                    reference_patterns=patterns,
                )
            else:
                latest_created_at = 0

            for root, _, files in os.walk(root_folder):
                for file in files:
                    file_path = os.path.normpath(os.path.join(root, file))

                    if file_path in ingested_paths:
                        continue

                    try:
                        file_mtime = int(os.path.getmtime(file_path))
                    except Exception:
                        continue
                    if file_mtime <= latest_created_at:
                        continue

                    try:
                        file_size = os.path.getsize(file_path)
                    except Exception:
                        continue
                    if file_size > max_file_size_mb * 1024 * 1024:
                        continue

                    d_file = DiscoveredFile(
                        name=os.path.basename(file_path),
                        reference=file_path,
                        file_size=file_size,
                        mime_type=mimetypes.guess_type(file_path)[0],
                        source_modified_at=file_mtime,
                    )

                    d_files.append(d_file)

        return d_files, None

    async def list_tree(self, path: str = "") -> Tuple[List[ResourceNode], bool]:
        """List immediate subfolders of *path* (empty = configured roots)."""
        credentials: OnboardingData = await self.get_credentials()
        roots = [path] if path else (credentials.root_folders or [os.getcwd()])
        return await asyncio.to_thread(self._build_tree_sync, roots)

    def _build_tree_sync(self, roots: List[str]) -> Tuple[List[ResourceNode], bool]:
        all_nodes: List[ResourceNode] = []

        for root in roots:
            try:
                entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
            except (PermissionError, FileNotFoundError):
                logger.warning(f"[LocalFilesIntegration] list_tree error at {root}", exc_info=True)
                continue

            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                file_count = 0
                has_children = False
                try:
                    for sub in os.scandir(entry.path):
                        if sub.is_dir(follow_symlinks=False):
                            has_children = True
                        else:
                            file_count += 1
                except (PermissionError, FileNotFoundError):
                    pass
                all_nodes.append(ResourceNode(
                    name=entry.name,
                    path=entry.path,
                    node_type="folder",
                    file_count=file_count,
                    has_children=has_children,
                ))

        return all_nodes, False


__all__ = ["LocalFilesIntegration"]
