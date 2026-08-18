"""Google Drive integration — incremental discovery over the Changes API.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from q99_utils.integrations.core import (
    SourceIntegrationInterface,
    classify_change,
    register,
    translate_refresh_error,
)
from q99_utils.integrations.discovery import ChangeKind, DiscoveredFile, ResourceNode
from q99_utils.models import PermissionTokens

from q99_utils.logger import get_logger
from q99_utils.enums import SourceEnum
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"

GOOGLE_NATIVE_EXPORTS = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.drawing": "image/png",
}


def _is_google_native(mime: str) -> bool:
    return (mime or "").startswith("application/vnd.google-apps.")


def _has_no_export_format(mime: str) -> bool:
    return _is_google_native(mime) and mime not in GOOGLE_NATIVE_EXPORTS


class FolderNameNotFound(ValueError):
    """Raised when a Drive name lookup returns no matches.

    Subclasses ValueError so callers that already catch ValueError keep
    working; the distinct type lets resolve_folder_id discriminate
    "name is not in Drive" (try ID fallback) from "lookup failed for
    some other reason" (propagate).
    """


class ChangesTokenExpired(Exception):
    """Drive Changes API returned 410 — stored page token has been purged.

    Signals files_discovery to clear the token and fall back to a full sync.
    """


@register(SourceEnum.googledrive)
class GoogleDriveIntegration(SourceIntegrationInterface):

    # Permissions

    @classmethod
    def _extract_permissions(cls, item: Dict[str, Any]) -> List[str]:
        perms = item.get("permissions") or []
        tokens: set[str] = set()

        for perm in perms:
            role = (perm.get("role") or "").lower()
            if role:
                tokens.add(f"role:{role}")

            p_type = (perm.get("type") or "").lower()
            if p_type == "user" and perm.get("emailAddress"):
                tokens.add(PermissionTokens.email(perm["emailAddress"]))
            elif p_type == "group" and perm.get("emailAddress"):
                tokens.add(PermissionTokens.group_for_source(SourceEnum.googledrive, perm["emailAddress"]))
            elif p_type == "domain" and perm.get("domain"):
                tokens.add(PermissionTokens.domain(perm["domain"]))
            elif p_type == "anyone":
                tokens.add(PermissionTokens.AUTHENTICATED)

        return sorted(tokens)

    # Auth and client

    async def get_access_token(self, data: OnboardingData):
        return Credentials(
            token=data.api_key,
            refresh_token=data.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=data.client_id,
            client_secret=data.client_secret,
        )

    async def get_service(self, service_name: str, credentials: OnboardingData, version: str = "v3"):
        access = await self.get_access_token(credentials)
        try:
            return build(service_name, version, credentials=access)
        except Exception:
            logger.exception("Unable to connect to Google Drive Integration.")
            return None

    # File download

    async def get_files_from_path(
        self,
        file_path: str,
        metadata: Dict[str, Any] = None,
        config: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs,
    ):
        credentials: OnboardingData = await self.get_credentials()
        service = await self.get_service(service_name="drive", credentials=credentials)

        file_id = file_path.split("/", 1)[1] if "/" in file_path else file_path

        mime_type = (metadata or {}).get("mime_type") or (metadata or {}).get("mimeType")
        if not mime_type:
            meta = await asyncio.to_thread(
                lambda: service.files().get(
                    fileId=file_id, fields="mimeType", supportsAllDrives=True,
                ).execute()
            )
            mime_type = meta.get("mimeType")

        export_mime = GOOGLE_NATIVE_EXPORTS.get(mime_type)

        def _sync_download():
            if export_mime:
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
            else:
                request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            file_buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(file_buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            file_buffer.seek(0)
            return file_buffer

        return await asyncio.to_thread(_sync_download)

    # File discovery

    async def files_discovery(self) -> Tuple[List[DiscoveredFile], dict]:
        """The one door in, so a revoked Drive is not read as a source without files."""
        try:
            return await self._files_discovery()
        except RefreshError as exc:
            translate_refresh_error(exc, source=self.source)

    async def _files_discovery(self) -> Tuple[List[DiscoveredFile], dict]:
        store = self.context.file_store

        credentials: OnboardingData = await self.get_credentials()
        max_file_size_mb: int = self.config.upload_max_size_mb
        root_folders = credentials.root_folders or []

        if self.credential_id and store:
            ingested_refs = await store.indexed_files(
                credential_id=self.credential_id,
                source=str(SourceEnum.googledrive),
            )
            ingested_hashes = await store.known_content_hashes(credential_id=self.credential_id)
        else:
            ingested_refs = {}
            ingested_hashes = set()

        d_files: List[DiscoveredFile] = []
        service = await self.get_service(service_name="drive", credentials=credentials)

        cursors_local: dict = await self.load_sync_cursors()

        stored_token = cursors_local.get("gdrive_changes_token") if self.credential_id else None

        effective_roots = [str(r or "").strip() for r in (root_folders if root_folders else [""])]

        new_roots = await self._roots_needing_full_scan(effective_roots)

        if new_roots:
            logger.info(f"[GoogleDriveIntegration] New roots detected, running full sync for: {new_roots}")
            for root_selector in new_roots:
                folder_id = await self.resolve_folder_id(service=service, selector=root_selector)
                await asyncio.to_thread(
                    self._discover_folder_recursive,
                    service=service,
                    folder_id=folder_id,
                    root_selector=root_selector,
                    d_files=d_files,
                    ingested_refs=ingested_refs,
                    ingested_hashes=ingested_hashes,
                    max_file_size_mb=max_file_size_mb,
                    latest_created_at=0,
                    credentials=credentials,
                )

        token_expired = False

        if stored_token:
            root_folder_to_selector: Dict[str, str] = {}
            for rs in effective_roots:
                try:
                    fid = await self.resolve_folder_id(service=service, selector=rs)
                    if fid and fid != "root":
                        root_folder_to_selector[fid] = rs
                except Exception:
                    logger.warning("[GoogleDriveIntegration] resolve_folder_id failed", exc_info=True, extra={"selector": str(rs)})

            try:
                new_token = await asyncio.to_thread(
                    self._discover_via_changes,
                    service=service,
                    page_token=stored_token,
                    root_folder_to_selector=root_folder_to_selector,
                    d_files=d_files,
                    ingested_refs=ingested_refs,
                    ingested_hashes=ingested_hashes,
                    max_file_size_mb=max_file_size_mb,
                )
            except ChangesTokenExpired:
                logger.warning(
                    f"[GoogleDriveIntegration] Changes page token expired for credential='{self.credential_id}' — falling back to full sync"
                )
                if self.credential_id:
                    cursors_local.pop("gdrive_changes_token", None)
                token_expired = True
                new_token = None

            if new_token and self.credential_id:
                cursors_local["gdrive_changes_token"] = new_token

        if (not stored_token and not new_roots) or token_expired:
            for root_selector in effective_roots:
                folder_id = await self.resolve_folder_id(service=service, selector=root_selector)
                await asyncio.to_thread(
                    self._discover_folder_recursive,
                    service=service,
                    folder_id=folder_id,
                    root_selector=root_selector,
                    d_files=d_files,
                    ingested_refs=ingested_refs,
                    ingested_hashes=ingested_hashes,
                    max_file_size_mb=max_file_size_mb,
                    latest_created_at=0,
                    credentials=credentials,
                )

        if new_roots or not stored_token or token_expired:
            if self.credential_id:
                try:
                    result = await asyncio.to_thread(
                        lambda: service.changes().getStartPageToken(supportsAllDrives=True).execute()
                    )
                    start_token = result.get("startPageToken")
                    if start_token:
                        cursors_local["gdrive_changes_token"] = start_token
                        logger.info(f"[GoogleDriveIntegration] Stored changes start token for credential='{self.credential_id}'")
                except Exception:
                    logger.warning("[GoogleDriveIntegration] Could not get changes start token", exc_info=True)

        return d_files, cursors_local

    def _discover_folder_recursive(
        self,
        service,
        folder_id: str,
        root_selector: str,
        d_files: List[DiscoveredFile],
        ingested_refs: Dict[str, Tuple[Optional[int], Optional[str], List[str]]],
        ingested_hashes: set,
        max_file_size_mb: int,
        latest_created_at: int,
        credentials: OnboardingData,
    ):
        def get_files_recursive(folder_id: str):
            nonlocal d_files

            latest_iso = datetime.fromtimestamp(latest_created_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")

            query = f"'{folder_id}' in parents and trashed=false and createdTime > '{latest_iso}'"
            fields = (
                "nextPageToken,files(id,name,mimeType,size,createdTime,modifiedTime,md5Checksum,parents,"
                "permissions(type,role,emailAddress,domain))"
            )

            next_page_token = None

            while True:
                try:
                    kwargs: dict = dict(
                        q=query,
                        fields=fields,
                        pageSize=1000,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    if next_page_token:
                        kwargs["pageToken"] = next_page_token
                    result = service.files().list(**kwargs).execute()

                    items = result.get("files", [])

                    for item in items:
                        if item["mimeType"] == FOLDER_MIME:
                            get_files_recursive(item["id"])
                            continue

                        item_mime = item.get("mimeType") or ""
                        if _has_no_export_format(item_mime):
                            continue

                        reference = f"{root_selector}/{item['id']}" if root_selector else item["id"]

                        file_size = int(item.get("size", 0))
                        if file_size > max_file_size_mb * 1024 * 1024:
                            continue

                        content_hash = item.get("md5Checksum")

                        source_modified_at = None
                        modified_str = item.get("modifiedTime")
                        if modified_str:
                            source_modified_at = int(
                                datetime.fromisoformat(
                                    modified_str.replace("Z", "+00:00")
                                ).timestamp()
                            )

                        source_perms = self._extract_permissions(item)
                        is_native_doc = _is_google_native(item_mime)

                        change_kind = ChangeKind.ADDED
                        if reference in ingested_refs:
                            stored_modified_at, stored_hash, stored_perms = ingested_refs[reference]
                            change_kind = classify_change(
                                stored_modified_at=stored_modified_at,
                                stored_hash=stored_hash,
                                stored_perms=stored_perms,
                                content_hash=content_hash,
                                source_modified_at=source_modified_at,
                                source_perms=source_perms,
                                perm_change_wins=is_native_doc,
                            )
                            if change_kind is None:
                                continue
                        elif content_hash and content_hash in ingested_hashes:
                            continue

                        if content_hash and change_kind != ChangeKind.PERMISSIONS_CHANGED:
                            ingested_hashes.add(content_hash)

                        d_files.append(DiscoveredFile(
                            name=item["name"],
                            reference=reference,
                            permissions=source_perms,
                            content_hash=content_hash,
                            file_size=file_size,
                            mime_type=item.get("mimeType"),
                            source_modified_at=source_modified_at,
                            change_kind=change_kind,
                        ))

                    next_page_token = result.get("nextPageToken")
                    if not next_page_token:
                        break

                except HttpError as e:
                    if e.resp.status == 404:
                        raise ValueError(f"Folder not found: {folder_id}") from e
                    raise

        get_files_recursive(folder_id)

    def _discover_via_changes(
        self,
        service,
        page_token: str,
        root_folder_to_selector: Dict[str, str],
        d_files: List[DiscoveredFile],
        ingested_refs: Dict[str, Tuple[Optional[int], Optional[str], List[str]]],
        ingested_hashes: set,
        max_file_size_mb: int,
    ) -> Optional[str]:
        """Incremental discovery using Drive Changes API.

        Paginates through all changes since *page_token* and returns the new
        page token to store for the next run.

        Root scoping walks the parent chain of each changed file using a shared
        cache, so each folder id is resolved at most once per run.
        """
        parent_cache: Dict[str, List[str]] = {}

        def _matching_root_selector(parents: List[str]) -> Optional[str]:
            """Return the configured selector for the root this file lives under.

            Empty string means "no scope constraint configured, use bare file_id".
            None means "file is outside every configured root — skip it".
            """
            if not root_folder_to_selector:
                return ""  # unconstrained
            to_check = list(parents)
            visited: set = set()
            while to_check:
                fid = to_check.pop()
                if fid in visited:
                    continue
                visited.add(fid)
                if fid in root_folder_to_selector:
                    return root_folder_to_selector[fid]
                if fid in ("root", "my_drive"):
                    continue
                if fid not in parent_cache:
                    try:
                        meta = service.files().get(
                            fileId=fid, fields="parents", supportsAllDrives=True
                        ).execute()
                        parent_cache[fid] = meta.get("parents") or []
                    except Exception:
                        parent_cache[fid] = []
                to_check.extend(parent_cache[fid])
            return None

        ref_by_file_id: Dict[str, str] = {}
        for ref in ingested_refs.keys():
            fid_part = ref.rsplit("/", 1)[-1] if "/" in ref else ref
            ref_by_file_id[fid_part] = ref

        new_token: Optional[str] = None
        fields = (
            "nextPageToken,newStartPageToken,"
            "changes(removed,fileId,file(id,name,mimeType,size,modifiedTime,md5Checksum,parents,driveId,"
            "permissions(type,role,emailAddress,domain)))"
        )

        while page_token:
            try:
                result = service.changes().list(
                    pageToken=page_token,
                    fields=fields,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                ).execute()
            except HttpError as e:
                if e.resp.status == 410:
                    raise ChangesTokenExpired() from e
                logger.warning("[GoogleDriveIntegration] Changes API error", exc_info=True)
                break
            except Exception:
                logger.warning("[GoogleDriveIntegration] Changes API error", exc_info=True)
                break

            for change in result.get("changes", []):
                if change.get("removed"):
                    removed_id = change.get("fileId")
                    if not removed_id:
                        continue
                    reference = ref_by_file_id.get(removed_id)
                    if reference is not None:
                        d_files.append(DiscoveredFile(
                            name="",
                            reference=reference,
                            change_kind=ChangeKind.REMOVED,
                        ))
                    continue

                file = change.get("file")
                if not file:
                    continue
                if file.get("mimeType") == FOLDER_MIME:
                    continue

                change_mime = file.get("mimeType") or ""
                if _has_no_export_format(change_mime):
                    continue

                # Shared-drive files carry a driveId; My Drive files do not.
                if not root_folder_to_selector and file.get("driveId"):
                    continue

                file_id = file["id"]
                parents = file.get("parents") or []

                selector = _matching_root_selector(parents)
                if selector is None:
                    continue  # file lives outside every configured root

                reference = f"{selector}/{file_id}" if selector else file_id

                file_size = int(file.get("size", 0))
                if file_size > max_file_size_mb * 1024 * 1024:
                    continue

                content_hash = file.get("md5Checksum")

                source_modified_at = None
                modified_str = file.get("modifiedTime")
                if modified_str:
                    source_modified_at = int(
                        datetime.fromisoformat(modified_str.replace("Z", "+00:00")).timestamp()
                    )

                source_perms = self._extract_permissions(file)
                is_native_doc = _is_google_native(change_mime)

                change_kind = ChangeKind.ADDED
                if reference in ingested_refs:
                    stored_modified_at, stored_hash, stored_perms = ingested_refs[reference]
                    change_kind = classify_change(
                        stored_modified_at=stored_modified_at,
                        stored_hash=stored_hash,
                        stored_perms=stored_perms,
                        content_hash=content_hash,
                        source_modified_at=source_modified_at,
                        source_perms=source_perms,
                        perm_change_wins=is_native_doc,
                    )
                    if change_kind is None:
                        try:
                            fresh = service.files().get(
                                fileId=file_id,
                                fields="permissions(type,role,emailAddress,domain)",
                                supportsAllDrives=True,
                            ).execute()
                        except Exception:
                            logger.warning(
                                f"[GoogleDriveIntegration] permissions refresh failed for {file_id}",
                                exc_info=True,
                            )
                            continue
                        fresh_perms = self._extract_permissions(fresh)
                        if sorted(fresh_perms) == sorted(stored_perms or []):
                            continue
                        source_perms = fresh_perms
                        change_kind = ChangeKind.PERMISSIONS_CHANGED
                elif content_hash and content_hash in ingested_hashes:
                    continue

                if content_hash and change_kind != ChangeKind.PERMISSIONS_CHANGED:
                    ingested_hashes.add(content_hash)

                d_files.append(DiscoveredFile(
                    name=file["name"],
                    reference=reference,
                    permissions=source_perms,
                    content_hash=content_hash,
                    file_size=file_size,
                    mime_type=file.get("mimeType"),
                    source_modified_at=source_modified_at,
                    change_kind=change_kind,
                ))

            page_token = result.get("nextPageToken")
            new_token = result.get("newStartPageToken") or new_token

        return new_token

    # Folder resolution

    async def resolve_folder_path(self, service, name_path: str) -> str:
        """Resolve a slash-separated name path like 'Engineering/Reports' into a Drive folder ID.

        Walks each segment within its parent, so duplicate folder names in
        different locations are handled correctly.
        """
        segments = [s.strip() for s in name_path.strip("/").split("/") if s.strip()]
        if not segments:
            return "root"

        parent_id = "root"
        for segment in segments:
            escaped = segment.replace("'", "\\'")
            query = (
                f"'{parent_id}' in parents and "
                f"name='{escaped}' and "
                f"mimeType='{FOLDER_MIME}' and "
                f"trashed=false"
            )
            result = await asyncio.to_thread(
                lambda q=query: service.files().list(
                    q=q, fields="files(id)", pageSize=2,
                    supportsAllDrives=True, includeItemsFromAllDrives=True,
                ).execute()
            )
            files = result.get("files", [])
            if not files:
                raise ValueError(f"Folder '{segment}' not found under parent {parent_id}")
            parent_id = files[0]["id"]

        return parent_id

    async def resolve_folder_id(self, service, selector: str) -> str:
        """Resolve a folder selector into a Drive folder ID.

        selector can be:
          - empty (uses Drive root)
          - a name path like "Engineering/Reports"
          - a single folder name
          - (legacy) a raw Drive folder ID
        """
        if not selector or not str(selector).strip():
            return "root"

        candidate = str(selector).strip()

        if "/" in candidate:
            parent_id = "root"
            for segment in (s for s in candidate.split("/") if s.strip()):
                parent_id = await self.get_folder_id_by_name(
                    service=service, folder_name=segment, parent_id=parent_id,
                )
            return parent_id

        try:
            return await self.get_folder_id_by_name(service=service, folder_name=candidate)
        except FolderNameNotFound:
            pass

        meta = await asyncio.to_thread(
            lambda: service.files().get(
                fileId=candidate,
                fields="id,mimeType",
                supportsAllDrives=True,
            ).execute()
        )
        if meta.get("mimeType") != FOLDER_MIME:
            raise ValueError(f"'{selector}' is not a folder")
        return meta["id"]

    async def get_folder_id_by_name(self, service, folder_name: str, parent_id: str | None = None):
        if not folder_name or not str(folder_name).strip():
            return "root"

        escaped_folder_name = folder_name.replace("'", "\\'")

        query = f"name='{escaped_folder_name}' and mimeType='{FOLDER_MIME}' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        result = await asyncio.to_thread(
            lambda: service.files().list(
                q=query,
                fields="files(id,name,parents)",
                pageSize=100,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        )

        folders = result.get("files", [])

        if not folders:
            raise FolderNameNotFound(f"Folder '{folder_name}' not found")

        if len(folders) > 1:
            folder_info = [
                f"ID: {f['id']}, Parents: {f.get('parents', ['root'])}"
                for f in folders
            ]
            raise ValueError(f"Multiple folders named '{folder_name}' found:\n" + "\n".join(folder_info))

        return folders[0]["id"]

    # Tree browsing

    def _list_folder_children(self, service, folder_id: str) -> List[Dict[str, Any]]:
        """Fetch immediate subfolder metadata for a Drive folder (paginated).

        Only queries folders to keep API calls minimal. file_count is not
        available for Drive — listing all items per folder is too expensive.
        """
        query = f"'{folder_id}' in parents and mimeType='{FOLDER_MIME}' and trashed=false"
        fields = "nextPageToken,files(id,name)"
        folders: List[Dict[str, Any]] = []
        next_page_token = None

        while True:
            kwargs: dict = dict(
                q=query, fields=fields, pageSize=1000,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            )
            if next_page_token:
                kwargs["pageToken"] = next_page_token
            result = service.files().list(**kwargs).execute()
            folders.extend(result.get("files", []))
            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                break

        return sorted(folders, key=lambda f: f["name"].lower())

    async def list_tree(self, path: str = "") -> Tuple[List[ResourceNode], bool]:
        credentials: OnboardingData = await self.get_credentials()
        service = await self.get_service(service_name="drive", credentials=credentials)

        if path:
            folder_id = await self.resolve_folder_id(service=service, selector=path)
            name_path = path.strip("/")
        else:
            folder_id = "root"
            name_path = ""

        try:
            children_data = await asyncio.to_thread(self._list_folder_children, service, folder_id)
        except Exception:
            logger.warning(f"[GoogleDriveIntegration] list_tree error for {folder_id}", exc_info=True)
            return [], False

        return [
            ResourceNode(
                name=item["name"],
                path=f"{name_path}/{item['name']}" if name_path else item["name"],
                node_type="folder",
                has_children=True,
            )
            for item in children_data
        ], False


__all__ = [
    "GoogleDriveIntegration",
    "FolderNameNotFound",
    "ChangesTokenExpired",
    "GOOGLE_NATIVE_EXPORTS",
]
