"""Company Webex archive: attachments and transcripts through the customer's Service App."""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timedelta, timezone
from email.message import Message
from urllib.parse import quote, unquote

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core import SourceIntegrationInterface, register
from q99_utils.integrations.core.exceptions import (
    AppCredentialExpired, CredentialExpired, CredentialValidationError, IntegrationError, ResourceNotFound,
)
from q99_utils.integrations.discovery import ChangeKind, DiscoveredFile
from q99_utils.models import OnboardingData, PermissionTokens

from q99_utils.integrations.sources.webex_client import WEBEX_API, WebexClient
from q99_utils.integrations.sources.webex_content import (
    MAX_ATTACHMENT_BYTES,
    MAX_TRANSCRIPT_BYTES,
    attachment_decision,
    transcript_decision,
)


MAX_EVENT_PAGES = 2
UNMAPPED = "webex_archive:unmapped"


def _date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _filename(disposition: str | None) -> str:
    if not disposition:
        return ""
    header = Message()
    header["Content-Disposition"] = disposition
    return (header.get_filename() or "").replace("\\", "/").rsplit("/", 1)[-1]


def _attachment_ref(room_id: str, message_id: str, url: str) -> str:
    return f"room/{quote(room_id, safe='')}/message/{quote(message_id, safe='')}/attachment/{quote(url, safe='')}"


def _transcript_ref(meeting_id: str, transcript_id: str) -> str:
    return f"meeting/{quote(meeting_id, safe='')}/transcript/{quote(transcript_id, safe='')}"


@register(SourceEnum.webex_archive)
class WebexArchiveIntegration(SourceIntegrationInterface):
    async def client(self, data: OnboardingData | None = None) -> WebexClient:
        if data is not None:
            return WebexClient(data)
        credentials = await self.get_credentials()
        return WebexClient(credentials, on_refresh=self.persist_tokens)

    async def test_connection(self, data: OnboardingData | None = None) -> None:
        events = await (await self.client(data))._json("/events", params={"max": 1})
        if not isinstance(events.get("items"), list):
            raise CredentialValidationError("Webex did not return an events list.", source="webex_archive")

    async def _room_permissions(self, client: WebexClient, room_id: str) -> list[str]:
        """Fail closed if the provider cannot prove current membership."""
        try:
            response = await client._request("/memberships", params={"roomId": room_id, "max": 100})
            tokens: set[str] = set()
            while True:
                items = response.json().get("items")
                if not isinstance(items, list):
                    return [UNMAPPED]
                for member in items:
                    address = member.get("personEmail")
                    if isinstance(address, str) and "@" in address:
                        tokens.add(PermissionTokens.email(address))
                next_url = (response.links.get("next") or {}).get("url")
                if not next_url:
                    break
                response = await client._request("", absolute_url=next_url)
            return sorted(tokens) or [UNMAPPED]
        except (CredentialExpired, AppCredentialExpired):
            raise
        except (IntegrationError, ValueError):
            return [UNMAPPED]

    @staticmethod
    def _transcript_link(transcript_id: str) -> str:
        # Compliance Officer access uses the transcript download API directly.
        # The user-level /meetingTranscripts listing only covers that user's meetings.
        return f"{WEBEX_API}/meetingTranscripts/{quote(transcript_id, safe='')}/download?format=txt"

    async def _transcript_text(self, client: WebexClient, transcript_id: str) -> str | None:
        raw = (await client.download(self._transcript_link(transcript_id), MAX_TRANSCRIPT_BYTES)).decode("utf-8-sig")
        decision, clean = transcript_decision(raw)
        return clean if decision.accepted else None

    async def get_files_from_path(self, file_path: str, metadata=None, config=None, *args, **kwargs):
        client = await self.client()
        if file_path.startswith("room/") and "/attachment/" in file_path:
            url = unquote(file_path.split("/attachment/", 1)[1])
            return io.BytesIO(await client.download(url, MAX_ATTACHMENT_BYTES))
        if file_path.startswith("meeting/") and "/transcript/" in file_path:
            parts = file_path.split("/")
            if len(parts) != 4:
                raise ValueError("Invalid Webex transcript reference.")
            clean = await self._transcript_text(client, unquote(parts[3]))
            if clean is None:
                raise ResourceNotFound("Webex transcript has no indexable text.", source="webex_archive")
            return io.BytesIO(clean.encode("utf-8"))
        raise ValueError("Invalid Webex archive reference.")

    async def files_discovery(self) -> tuple[list[DiscoveredFile], dict]:
        client = await self.client()
        current = await self.load_sync_cursors()
        now = datetime.now(timezone.utc)
        next_url = current.get("webex_events_next")
        window_end = current.get("webex_events_to") or now.isoformat()
        since = current.get("webex_events_from") or (now - timedelta(days=30)).isoformat()
        known = await self.context.file_store.indexed_files(
            credential_id=self.credential_id, source=str(self.source),
        ) if self.credential_id and self.context.file_store else {}
        changes: list[DiscoveredFile] = []
        room_acl: dict[str, list[str]] = {}
        deleted_message_prefixes: set[str] = set(current.get("webex_deleted_messages") or [])

        async def acl(room_id: str) -> list[str]:
            if room_id not in room_acl:
                room_acl[room_id] = await self._room_permissions(client, room_id)
            return room_acl[room_id]

        for _ in range(MAX_EVENT_PAGES):
            response = await client._request(
                "" if next_url else "/events",
                absolute_url=next_url,
                params=None if next_url else {"from": since, "to": window_end, "max": 100},
            )
            events = response.json().get("items")
            if not isinstance(events, list):
                raise IntegrationError("Webex returned an invalid events page.")
            for event in events:
                data = event.get("data") or {}
                resource, kind = event.get("resource"), event.get("type")
                if resource == "messages" and kind == "created":
                    message_id, room_id = data.get("id"), data.get("roomId")
                    if not (message_id and room_id):
                        continue
                    message = await client._json(f"/messages/{quote(message_id, safe='')}")
                    for url in message.get("files") or []:
                        details = await client.file_details(url)
                        name = _filename(details.get("content_disposition"))
                        try:
                            size = int(details["content_length"]) if details.get("content_length") else None
                        except ValueError:
                            size = None
                        if not attachment_decision(name, size, details.get("content_type")).accepted:
                            continue
                        ref = _attachment_ref(room_id, message_id, url)
                        if ref in known:
                            continue
                        changes.append(DiscoveredFile(
                            name=name, reference=ref, file_size=size,
                            mime_type=details.get("content_type"),
                            source_modified_at=_date(event.get("created")),
                            permissions=await acl(room_id),
                        ))
                elif resource == "messages" and kind == "deleted":
                    message_id, room_id = data.get("id"), data.get("roomId")
                    if not (message_id and room_id):
                        continue
                    prefix = f"room/{quote(room_id, safe='')}/message/{quote(message_id, safe='')}/attachment/"
                    deleted_message_prefixes.add(prefix)
                    changes.extend(
                        DiscoveredFile(name=ref.rsplit("/", 1)[-1], reference=ref, change_kind=ChangeKind.REMOVED)
                        for ref in known if ref.startswith(prefix)
                    )
                elif resource == "meetingTranscripts" and kind == "created":
                    meeting_id, transcript_id = data.get("meetingId"), data.get("id")
                    if not (meeting_id and transcript_id):
                        continue
                    clean = await self._transcript_text(client, transcript_id)
                    if clean is None:
                        continue
                    ref = _transcript_ref(meeting_id, transcript_id)
                    host = data.get("hostEmail")
                    permissions = [PermissionTokens.email(host)] if isinstance(host, str) and "@" in host else [UNMAPPED]
                    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
                    previous = known.get(ref)
                    if previous and previous.content_hash == digest and previous.permissions == permissions:
                        continue
                    changes.append(DiscoveredFile(
                        name=f"Webex transcript {meeting_id}.txt", reference=ref,
                        mime_type="text/plain", file_size=len(clean.encode("utf-8")),
                        content_hash=digest, source_modified_at=_date(event.get("created")),
                        permissions=permissions,
                        change_kind=ChangeKind.UPDATED if previous else ChangeKind.ADDED,
                    ))
                elif resource == "memberships" and kind in {"created", "deleted", "updated"}:
                    room_id = data.get("roomId")
                    if room_id:
                        room_acl.pop(room_id, None)
                        prefix = f"room/{quote(room_id, safe='')}/"
                        permissions = await acl(room_id)
                        changes.extend(
                            DiscoveredFile(name=ref.rsplit("/", 1)[-1], reference=ref,
                                           permissions=permissions, change_kind=ChangeKind.PERMISSIONS_CHANGED)
                            for ref, old in known.items()
                            if ref.startswith(prefix) and old.permissions != permissions
                        )
            next_url = (response.links.get("next") or {}).get("url")
            if not next_url:
                break

        # Event pages may arrive newest first. A deletion wins even when the
        # corresponding creation appeared on a later page of the same window.
        if deleted_message_prefixes:
            changes = [
                change for change in changes
                if change.change_kind == ChangeKind.REMOVED
                or not any(change.reference.startswith(prefix) for prefix in deleted_message_prefixes)
            ]

        # A completed window advances; a partial one resumes exactly at the next page.
        if next_url:
            current.update(webex_events_next=next_url, webex_events_from=since, webex_events_to=window_end)
            current["webex_deleted_messages"] = sorted(deleted_message_prefixes)
        else:
            current.pop("webex_events_next", None)
            current.pop("webex_events_to", None)
            current.pop("webex_deleted_messages", None)
            current["webex_events_from"] = window_end
        return changes, current


__all__ = ["WebexArchiveIntegration"]
