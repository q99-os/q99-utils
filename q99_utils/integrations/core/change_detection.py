"""What changed about an already-indexed file. Shared by SharePoint and Drive."""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from q99_utils.integrations.discovery import ChangeKind, DiscoveredFile


def classify_change(
    *,
    stored_modified_at: Optional[int],
    stored_hash: Optional[str],
    stored_perms: Optional[List[str]],
    content_hash: Optional[str],
    source_modified_at: Optional[int],
    source_perms: List[str],
    perm_change_wins: bool = False,
) -> Optional[ChangeKind]:
    """What changed about a reference the host already holds, or None.

    ``None`` means nothing actionable changed — the caller decides whether that
    is a skip or a reason to look closer.

    Content wins over permissions when both moved: a re-ingest rewrites the
    permissions anyway. Hashes are compared first because they are exact;
    modification time is the fallback for providers that don't always supply one.

    ``perm_change_wins`` suppresses the mtime comparison when permissions also
    changed. Providers bump the modification time on an ACL edit for some file
    kinds, and treating that as new content would re-ingest the file for
    nothing. Google Drive sets this only for its native docs; SharePoint sets
    it always.
    """
    perms_changed = sorted(source_perms) != sorted(stored_perms or [])

    if content_hash is not None and stored_hash is not None:
        content_changed = content_hash != stored_hash
    elif perm_change_wins and perms_changed:
        content_changed = False
    elif source_modified_at is not None and stored_modified_at is not None:
        content_changed = source_modified_at > stored_modified_at
    else:
        content_changed = False

    if content_changed:
        return ChangeKind.UPDATED
    if perms_changed:
        return ChangeKind.PERMISSIONS_CHANGED
    return None


def references_by_file_id(references: Iterable[str]) -> Dict[str, List[str]]:
    """Group stored references by the provider file ID they end in."""
    grouped: Dict[str, List[str]] = {}
    for ref in references:
        grouped.setdefault(ref.rsplit("/", 1)[-1], []).append(ref)
    return grouped


class IdentifiedChange(NamedTuple):
    change_kind: Optional[ChangeKind]
    previous_reference: Optional[str]
    stale_references: List[str]


def identify_change(
    *,
    reference: str,
    file_id: str,
    ingested_refs: Mapping[str, Tuple[Optional[int], Optional[str], List[str]]],
    refs_by_file_id: Mapping[str, Sequence[str]],
    ingested_hashes: Set[str],
    content_hash: Optional[str],
    source_modified_at: Optional[int],
    source_perms: List[str],
    perm_change_wins: bool = False,
) -> IdentifiedChange:
    """Decide what a discovered file is, keyed on the provider's file ID.

    A file already held under *reference* is classified as usual. The same file
    held under another reference was moved or its root was renamed: it keeps
    one row, renamed via ``previous_reference``. Any further rows for the same
    file ID are stale duplicates. A ``None`` change_kind means skip the file;
    ``stale_references`` still need removing.
    """
    known = [r for r in refs_by_file_id.get(file_id, ())]

    def _classify(stored) -> Optional[ChangeKind]:
        stored_modified_at, stored_hash, stored_perms = stored
        return classify_change(
            stored_modified_at=stored_modified_at,
            stored_hash=stored_hash,
            stored_perms=stored_perms,
            content_hash=content_hash,
            source_modified_at=source_modified_at,
            source_perms=source_perms,
            perm_change_wins=perm_change_wins,
        )

    if reference in ingested_refs:
        return IdentifiedChange(_classify(ingested_refs[reference]), None, [r for r in known if r != reference])

    if known:
        previous, stale = known[0], known[1:]
        return IdentifiedChange(_classify(ingested_refs[previous]) or ChangeKind.MOVED, previous, stale)

    if content_hash and content_hash in ingested_hashes:
        return IdentifiedChange(None, None, [])

    return IdentifiedChange(ChangeKind.ADDED, None, [])


def removals(references: Iterable[str]) -> List[DiscoveredFile]:
    """Removal records for references that no longer hold a live file."""
    return [DiscoveredFile(name="", reference=r, change_kind=ChangeKind.REMOVED) for r in references]


__all__ = ["classify_change", "identify_change", "references_by_file_id", "removals", "IdentifiedChange"]
