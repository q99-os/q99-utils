"""Port for reading what the host has already ingested.

``reference_patterns`` are SQL-LIKE patterns OR'd together. Each integration
builds its own, since path conventions differ per provider.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Protocol, Sequence, runtime_checkable


class IndexedFile(NamedTuple):
    """What the host knows about one already-ingested reference."""

    source_modified_at: Optional[int]
    content_hash: Optional[str]
    permissions: List[str]


@runtime_checkable
class FileReferenceStore(Protocol):
    """Read-only view over the host's ingested-file index.

    Watch which methods exclude soft-deleted rows. ``indexed_files`` and
    ``known_content_hashes`` drive change-detection and dedup, so a deleted row
    must not suppress a re-ingest. The rest answer "was this ever seen", where
    deleted rows still count.
    """

    async def known_references(
        self,
        *,
        credential_id: str,
        source: Optional[str] = None,
        reference_patterns: Optional[Sequence[str]] = None,
    ) -> set[str]:
        """Every reference stored for this credential. Includes deleted rows."""
        ...

    async def indexed_files(
        self,
        *,
        credential_id: str,
        source: Optional[str] = None,
        reference_patterns: Optional[Sequence[str]] = None,
    ) -> Dict[str, IndexedFile]:
        """Reference → what is known about it. Excludes deleted rows."""
        ...

    async def known_content_hashes(self, *, credential_id: str) -> set[str]:
        """Non-null content hashes for this credential. Excludes deleted rows."""
        ...

    async def latest_source_modified_at(
        self,
        *,
        credential_id: str,
        source: Optional[str] = None,
        reference_patterns: Optional[Sequence[str]] = None,
    ) -> int:
        """Newest provider-side modification time seen, or 0. Includes deleted rows."""
        ...

    async def latest_ingested_at(
        self,
        *,
        credential_id: str,
        reference_patterns: Optional[Sequence[str]] = None,
    ) -> int:
        """Newest local ingestion time seen, or 0. Includes deleted rows.

        When *we* stored the row, not when the provider last touched the file.
        Local files have no reliable provider timestamp, so they use this.
        """
        ...

    async def has_indexed_files(
        self,
        *,
        credential_id: str,
        source: Optional[str] = None,
        reference_patterns: Optional[Sequence[str]] = None,
    ) -> bool:
        """Whether anything matching is indexed. Used to detect a fresh root
        that needs a full scan instead of an incremental one."""
        ...


__all__ = ["FileReferenceStore", "IndexedFile"]
