"""What changed about an already-indexed file. Shared by SharePoint and Drive."""

from __future__ import annotations

from typing import List, Optional

from q99_utils.integrations.discovery import ChangeKind


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


__all__ = ["classify_change"]
