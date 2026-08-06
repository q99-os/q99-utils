"""SharePoint integration — incremental discovery over the Graph delta API."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

import httpx

from q99_utils.integrations.core import SourceIntegrationInterface, classify_change, register
from q99_utils.integrations.discovery import ChangeKind, DiscoveredFile, ResourceNode
from q99_utils.models import PermissionTokens

from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class _GraphRateLimiter:
    """Token-bucket rate limiter: allows up to `rate` requests per second."""

    def __init__(self, rate: float = 30.0) -> None:
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


@register(SourceEnum.sharepoint)
class SharepointIntegration(SourceIntegrationInterface):
    _rate_limiter = _GraphRateLimiter(rate=30.0)

    # Permissions

    @classmethod
    def _extract_permissions(
        cls,
        permissions_payload: List[dict] | None,
        group_names: Dict[str, List[str]] | None = None,
    ) -> List[str]:
        """Build Layer-2 ACL tokens from Graph driveItem permissions, in the
        vocabulary the host's security service matches: person grants →
        ``email:<email>``, Entra group grants → ``azure_ad:group:<name>``,
        org-wide/anonymous links → ``quantos:authenticated``. Site-local groups
        and role grants produce no token.

        ``group_names`` maps an Entra group id to its federatable names
        (displayName, mailNickname) from ``_resolve_group_names``; absent that,
        a group falls back to its email local-part.
        """
        group_names = group_names or {}
        tokens: set[str] = set()

        def _add_identity(identity: dict) -> None:
            group = identity.get("group") or {}
            if group:
                gid = group.get("id")
                names = list(group_names.get(gid) or []) if gid else []
                if not names:
                    email = (group.get("email") or "").strip().lower()
                    if "@" in email:
                        names = [email.split("@", 1)[0]]
                for name in names:
                    if name.strip():
                        tokens.add(PermissionTokens.group_for_source(SourceEnum.sharepoint, name))
                return
            user = identity.get("user") or identity.get("siteUser") or {}
            email = (user.get("email") or user.get("userPrincipalName") or "").strip()
            if email:
                tokens.add(PermissionTokens.email(email))

        for perm in permissions_payload or []:
            granted = perm.get("grantedToV2")
            if granted:
                _add_identity(granted)
            for identity in perm.get("grantedToIdentitiesV2") or []:
                _add_identity(identity)

            link = perm.get("link") or {}
            scope = str(link.get("scope") or "").strip().lower()
            if scope in ("anonymous", "organization"):
                tokens.add(PermissionTokens.AUTHENTICATED)

        return sorted(tokens)

    async def _resolve_group_names(
        self, client: httpx.AsyncClient, headers: dict, group_id: str
    ) -> List[str]:
        """Resolve an Entra group id to its federatable names (displayName,
        mailNickname) — the keys UM matches against. Returns ``[]`` for
        site-local groups or on error.
        """
        url = f"{GRAPH_BASE_URL}/groups/{group_id}?$select=displayName,mailNickname"
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        except Exception:
            logger.warning(
                f"[SharepointIntegration] group name resolution failed for id={group_id}",
                exc_info=True,
            )
            return []
        data = resp.json()
        names: List[str] = []
        for key in ("displayName", "mailNickname"):
            val = (data.get(key) or "").strip()
            if val and val not in names:
                names.append(val)
        return names

    @staticmethod
    def _root_like_pattern(root: str) -> str:
        """LIKE pattern matching everything stored under *root*.

        References are built as ``<root>/<driveItem id>`` with no leading
        slash, so the pattern must not have one either.
        """
        return f"{root}/%" if root else "%"

    @staticmethod
    def _is_path_in_scope(path: str, root_selectors: List[str] | str | None) -> bool:
        """Check if *path* falls within any of the given root selectors.

        Accepts a single string (legacy / permission-sync callers), a list, or None.
        """
        if root_selectors is None:
            return True
        if isinstance(root_selectors, str):
            root_selectors = [root_selectors]
        roots = [r.strip().strip("/") for r in root_selectors if r and r.strip()]
        if not roots:
            return True
        clean = path.strip("/")
        return any(clean == r or clean.startswith(r + "/") for r in roots)

    async def _fetch_item_permissions(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        site_id: str,
        item_id: str,
        group_name_cache: Dict[str, List[str]],
    ) -> List[str]:
        url = f"{GRAPH_BASE_URL}/sites/{site_id}/drive/items/{item_id}/permissions"
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        payload = resp.json().get("value") or []

        for perm in payload:
            identities = []
            granted = perm.get("grantedToV2")
            if granted:
                identities.append(granted)
            identities.extend(perm.get("grantedToIdentitiesV2") or [])
            for identity in identities:
                gid = (identity.get("group") or {}).get("id")
                if gid and gid not in group_name_cache:
                    group_name_cache[gid] = await self._resolve_group_names(client, headers, gid)

        return self._extract_permissions(payload, group_name_cache)

    # Auth

    async def get_access_token(self, data: Optional[OnboardingData] = None):
        if data:
            self.credentials = data.model_dump()
        else:
            await self.get_credentials()  # first onboarding: read them from UM
        tenant_id = self.credentials["tenant_id"]
        client_id = self.credentials["client_id"]
        client_secret = self.credentials["client_secret"]

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        token_data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": GRAPH_SCOPE,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(token_url, data=token_data)
            response.raise_for_status()
            token = response.json().get("access_token")

        return token

    # File discovery

    async def files_discovery(self) -> Tuple[List[DiscoveredFile], dict]:
        store = self.context.file_store
        max_file_size_mb: int = self.config.upload_max_size_mb

        credentials: OnboardingData = await self.get_credentials()
        access_token = await self.get_access_token(credentials)

        root_folders = credentials.root_folders or []
        root_selectors = [str(r or "").strip().strip("/") for r in root_folders if r and str(r).strip()]

        if self.credential_id and store:
            ingested_refs = await store.indexed_files(
                credential_id=self.credential_id,
                source=str(SourceEnum.sharepoint),
                reference_patterns=[self._root_like_pattern(rs) for rs in root_selectors] or None,
            )
            ingested_hashes = await store.known_content_hashes(credential_id=self.credential_id)
        else:
            ingested_refs = {}
            ingested_hashes = set()

        d_files = []

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        cursors_local: dict = await self.load_sync_cursors()

        effective_roots = root_selectors if root_selectors else [""]

        new_roots = await self._roots_needing_full_scan(effective_roots)

        async with httpx.AsyncClient(timeout=120) as client:

            async def _graph_get(url: str, params: dict | None = None) -> dict:
                """Rate-limited GET with 429 exponential backoff."""
                await self._rate_limiter.acquire()
                for attempt in range(5):
                    response = await client.get(url, headers=headers, params=params)
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                        logger.warning(f"[SharepointIntegration] 429 rate-limited, retrying in {retry_after}s")
                        await asyncio.sleep(retry_after)
                        await self._rate_limiter.acquire()
                        continue
                    response.raise_for_status()
                    return response.json()
                response.raise_for_status()  # raise after exhausting retries

            async def _fetch_all_items(start_url: str) -> tuple[list, str | None]:
                """Paginate through a drive delta URL, return (items, deltaLink)."""
                all_items: list = []
                delta_link: str | None = None
                next_link: str | None = start_url
                while next_link:
                    r_data = await _graph_get(next_link)
                    all_items.extend(r_data.get("value", []))
                    next_link = r_data.get("@odata.nextLink")
                    if not next_link:
                        delta_link = r_data.get("@odata.deltaLink")
                return all_items, delta_link

            drive = await _graph_get(f"{GRAPH_BASE_URL}/sites/{credentials.site_id}/drive")
            drive_id = drive.get("id")
            delta_key = f"sharepoint_delta:{drive_id}"
            delta_url = f"{GRAPH_BASE_URL}/sites/{credentials.site_id}/drive/root/delta"

            if new_roots and self.credential_id:
                logger.info(f"[SharepointIntegration] New roots detected {new_roots}, clearing delta token for full rescan")
                cursors_local.pop(delta_key, None)

            stored_delta = cursors_local.get(delta_key) if self.credential_id else None
            start_url = stored_delta or delta_url

            try:
                all_items, new_delta_link = await _fetch_all_items(start_url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 410:
                    logger.warning(f"[SharepointIntegration] Delta token expired for drive={drive_id}, falling back to full sync")
                    if self.credential_id:
                        cursors_local.pop(delta_key, None)
                    all_items, new_delta_link = await _fetch_all_items(delta_url)
                else:
                    raise

            if new_delta_link and self.credential_id:
                cursors_local[delta_key] = new_delta_link

            ref_by_item_id = {ref.rsplit("/", 1)[-1]: ref for ref in ingested_refs}
            group_name_cache: Dict[str, List[str]] = {}
            for item in all_items:
                item_id = item.get("id")

                if item.get("deleted"):
                    ref = ref_by_item_id.get(item_id)
                    if ref:
                        d_files.append(DiscoveredFile(
                            name="",
                            reference=ref,
                            change_kind=ChangeKind.REMOVED,
                        ))
                    continue

                file_facet = item.get("file")
                if not file_facet:
                    continue  # drive root, folder, or package — no downloadable content

                name = item.get("name")
                parent_path = (item.get("parentReference") or {}).get("path") or ""
                rel_parent = unquote(parent_path.split("root:", 1)[1]) if "root:" in parent_path else ""
                clean_path = f"{rel_parent}/{name}".strip("/") if name else rel_parent.strip("/")

                matched_root = next(
                    (r for r in root_selectors if clean_path == r or clean_path.startswith(r + "/")),
                    None,
                )
                if root_selectors and matched_root is None:
                    continue
                reference = f"{matched_root}/{item_id}" if matched_root else item_id

                if (item.get("size") or 0) > max_file_size_mb * 1024 * 1024:
                    continue

                hashes = file_facet.get("hashes") or {}
                content_hash = hashes.get("quickXorHash") or hashes.get("sha256Hash")

                source_modified_at = None
                last_modified_str = item.get("lastModifiedDateTime")
                if last_modified_str:
                    source_modified_at = int(
                        datetime.fromisoformat(
                            last_modified_str.replace("Z", "+00:00")
                        ).timestamp()
                    )

                try:
                    permissions = await self._fetch_item_permissions(
                        client=client,
                        headers=headers,
                        site_id=credentials.site_id,
                        item_id=item["id"],
                        group_name_cache=group_name_cache,
                    )
                except Exception:
                    logger.warning(
                        f"[SharepointIntegration] Failed ACL fetch for reference='{reference}' — skipping; will retry on next discovery", exc_info=True
                    )
                    continue

                change_kind = ChangeKind.ADDED
                if reference in ingested_refs:
                    stored_modified_at, stored_hash, stored_perms = ingested_refs[reference]
                    change_kind = classify_change(
                        stored_modified_at=stored_modified_at,
                        stored_hash=stored_hash,
                        stored_perms=stored_perms,
                        content_hash=content_hash,
                        source_modified_at=source_modified_at,
                        source_perms=permissions,
                        perm_change_wins=True,
                    )
                    if change_kind is None:
                        continue
                elif content_hash and content_hash in ingested_hashes:
                    continue

                if content_hash and change_kind != ChangeKind.PERMISSIONS_CHANGED:
                    ingested_hashes.add(content_hash)

                d_file = DiscoveredFile(
                    name=name,
                    reference=reference,
                    permissions=permissions,
                    content_hash=content_hash,
                    file_size=item.get("size"),
                    mime_type=mimetypes.guess_type(name)[0],
                    source_modified_at=source_modified_at,
                    change_kind=change_kind,
                )
                d_files.append(d_file)

        return d_files, cursors_local

    # File download

    async def get_files_from_path(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs,
    ):
        config = config or {}
        access_token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}
        site_id = self.credentials["site_id"]
        item_id = file_path.rsplit("/", 1)[-1]
        url = f"{GRAPH_BASE_URL}/sites/{site_id}/drive/items/{item_id}/content"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(url, headers=headers, follow_redirects=True)
                response.raise_for_status()
        except Exception:
            logger.warning(f"Failed to fetch remote file at {url}", exc_info=True)
            return None

        content_disposition = response.headers.get("Content-Disposition", "")
        content = response.content

        if content_disposition and "filename=" in content_disposition:
            filename = content_disposition.split("filename=")[-1].strip('"')
        else:
            filename = file_path.split("/")[-1]
        _, file_extension = os.path.splitext(filename)
        file_extension = file_extension.lstrip(".")

        if "file_format" in config and file_extension not in config["file_format"]:
            return None

        return io.BytesIO(content)

    # Site metadata

    async def get_site_id(self, data: OnboardingData):
        url = f"{GRAPH_BASE_URL}/sites/{data.tenant_name}.sharepoint.com:/sites/{data.site_name}"
        access_token = await self.get_access_token(data=data)

        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url=url, headers=headers)
            response.raise_for_status()
            id_value = response.json()["id"]

        return id_value

    async def get_lists(self, data: OnboardingData, access_token: str):
        url = f"{GRAPH_BASE_URL}/sites/{data.site_id}/lists"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url=url, headers=headers)
            response.raise_for_status()
            values = response.json()

        return values["value"]

    async def list_tree(self, path: str = "") -> Tuple[List[ResourceNode], bool]:
        credentials: OnboardingData = await self.get_credentials()
        access_token = await self.get_access_token(credentials)

        site_id = credentials.site_id
        headers = {"Authorization": f"Bearer {access_token}"}

        clean = path.strip("/")
        if clean:
            url = f"{GRAPH_BASE_URL}/sites/{site_id}/drive/root:/{clean}:/children"
        else:
            url = f"{GRAPH_BASE_URL}/sites/{site_id}/drive/root/children"

        nodes: List[ResourceNode] = []
        next_url: Optional[str] = url

        async with httpx.AsyncClient(timeout=60.0) as client:
            while next_url:
                try:
                    resp = await client.get(next_url, headers=headers)
                    resp.raise_for_status()
                except Exception:
                    logger.warning(f"[SharepointIntegration] list_tree error at {path}", exc_info=True)
                    break
                data = resp.json()

                for item in data.get("value", []):
                    folder = item.get("folder")
                    if folder is None:
                        continue
                    item_name = item["name"]
                    nodes.append(ResourceNode(
                        name=item_name,
                        path=f"{clean}/{item_name}".lstrip("/"),
                        node_type="folder",
                        has_children=(folder.get("childCount", 0) > 0),
                    ))

                next_url = data.get("@odata.nextLink")

        return nodes, False


__all__ = ["SharepointIntegration"]
