"""Types that cross the boundary between an integration and its host."""

from __future__ import annotations

from enum import StrEnum
from typing import List, Literal, Optional

from pydantic import BaseModel


class ChangeKind(StrEnum):
    """How a discovered file changed relative to what the host already knows."""

    ADDED = "added"
    UPDATED = "updated"
    PERMISSIONS_CHANGED = "permissions_changed"
    REMOVED = "removed"


class DiscoveredFile(BaseModel):
    """A single file surfaced by ``files_discovery()``."""

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


class PermissionTokens:
    """Canonical Layer-2 ACL token vocabulary, shared by the user side
    (the host's security service) and the file side (each integration's
    ``_extract_permissions``) so the token format lives in one place.

    Group tokens are scoped by identity provider — ``<scope>:group:<name>`` —
    so groups from different providers can't collide.
    """

    AUTHENTICATED = "quantos:authenticated"
    ADMIN_ONLY = "quantos:group:quantos-admin"
    APP_SCOPE = "quantos"

    # Identity provider that owns each integration source's group grants.
    _GROUP_SCOPE_BY_SOURCE = {
        "sharepoint": "azure_ad",
        "googledrive": "google_workspace",
    }

    @classmethod
    def group_scope_for_source(cls, source: str) -> str:
        return cls._GROUP_SCOPE_BY_SOURCE.get(str(source), str(source))

    @staticmethod
    def group(scope: str, name: str) -> str:
        return f"{scope}:group:{name.strip().lower()}"

    @classmethod
    def group_for_source(cls, source: str, name: str) -> str:
        return cls.group(cls.group_scope_for_source(source), name)

    @staticmethod
    def email(address: str) -> str:
        return f"email:{address.strip().lower()}"

    @staticmethod
    def domain(value: str) -> str:
        return f"domain:{value.strip().lower()}"


# Legacy alias; drop once every caller uses DiscoveredFile.
discoveredFile = DiscoveredFile


__all__ = [
    "ChangeKind",
    "DiscoveredFile",
    "discoveredFile",
    "ResourceNode",
    "PermissionTokens",
]
