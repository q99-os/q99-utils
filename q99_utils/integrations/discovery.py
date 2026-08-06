from __future__ import annotations

from enum import StrEnum
from typing import List, Literal, Optional

from pydantic import BaseModel


class ChangeKind(StrEnum):
    ADDED = "added"
    UPDATED = "updated"
    PERMISSIONS_CHANGED = "permissions_changed"
    REMOVED = "removed"


class DiscoveredFile(BaseModel):
    name: str
    reference: str
    permissions: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    content_hash: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    source_modified_at: Optional[int] = None
    change_kind: ChangeKind = ChangeKind.ADDED


class ResourceNode(BaseModel):
    """A folder node returned by ``list_tree()`` (file_system sources only).

    has_children: folder worth expanding. file_count: files directly inside
    (0 if the provider can't report it cheaply). children: unused single-level.
    """

    name: str
    path: str
    node_type: Literal["file", "folder"]
    permissions: List[str] = []
    children: List[ResourceNode] = []
    has_children: bool = False
    file_count: int = 0
    selected: bool = False  # True if this path is in the credential's stored_roots


ResourceNode.model_rebuild()


# Legacy alias; drop once every caller uses DiscoveredFile.
discoveredFile = DiscoveredFile


__all__ = ["ChangeKind", "DiscoveredFile", "discoveredFile", "ResourceNode"]
