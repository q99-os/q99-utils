from fastapi import HTTPException, status
from typing import List, Literal, Optional
import httpx

from q99_utils.environment import USER_MANAGER_URL
from q99_utils.models import (
    OnboardingData, UMMessage, UMTrace, UMTraceGroup, UMExport, UMCrontab, UMTaskSchedule,
    UMReport, UMReportSection,
)

class UserManagerSDK:
    def __init__(self, access_token: str | None = None, *, api_key: str | None = None) -> None:
        if access_token and api_key:
            raise ValueError("Pass either access_token or api_key, not both")
        self.access_token = access_token
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict = None,
        params: dict = None,
        json: dict = None,
        clean_output: bool = False
    ):
        headers = headers or {}
        if self.access_token:
            headers["Authorization"] = self.access_token
        elif self.api_key:
            headers["Authorization"] = f"Api-Key {self.api_key}"

        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"User Manager unavailable: {exc}"
            )# UM does not respond

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json(),
            )
        if response.status_code == 204 or not response.content:
            return None

        if clean_output:
            raw_string = response.content.decode('utf-8').strip('"')
            cleaned_config_data = raw_string.encode('utf-8').decode('unicode_escape')
            return cleaned_config_data
        
        return response.json()

    async def get_credential(
        self,
        credential_id: str | None = None,
        source: str | None = None,
        integration_type: str | None = None
    ):
        if credential_id:
            url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"
            return await self._request(method="GET", url=url)
        
        url = f"{USER_MANAGER_URL}/v1/credentials/"
        params = {}
        if source:
            params["source"] = source
        if integration_type:
            params["integration-type"] = integration_type
        return await self._request(method="GET", url=url, params=params)

    async def post_credentials(self, data: OnboardingData):
        url = f"{USER_MANAGER_URL}/v1/credentials/"
        
        return await self._request(method="POST", url=url, json=data.model_dump(exclude_none=True))

    async def update_credentials(self, data, credential_id: str):
        update_url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"

        return await self._request(method="PATCH", url=update_url, json=data.model_dump(exclude_none=True))

    async def update_root_folders(self, credential_id: str, root_folders: list):
        patch_url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"
        return await self._request(method="PATCH", url=patch_url, json={"root_folders": root_folders})

    async def update_sync_state(self, credential_id: str, sync_cursors: dict, last_sync: str):
        patch_url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"
        return await self._request(
            method="PATCH",
            url=patch_url,
            json={"sync_cursors": sync_cursors, "last_sync": last_sync},
        )

    async def activate_credential(self, credential_id:str):
        patch_url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"

        return await self._request(method="PATCH", url=patch_url, json={"is_active": True})

    async def deactivate_credential(self, credential_id:str):
        patch_url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"

        return await self._request(method="PATCH", url=patch_url, json={"is_active": False})

    async def validate_token(
        self,
        *,
        staff_required: bool = False,
        permissions_required: list[str] | None = None,
    ):
        """Ask UM to validate the caller's token against optional policy gates.

        Both gates are independent and combine with AND semantics on the UM
        side: a request must satisfy every declared gate to receive a 200.

        - ``staff_required=True`` — the user must have ``is_staff=True``.
        - ``permissions_required=[...]`` — the user must hold ALL listed
          codenames (set-subset check). Pass bare codenames like
          ``"files:read"`` — UM adds the service namespace itself.

        Both arguments are optional; omitting both reduces to a plain
        "is this token valid for an active user?" check (the legacy behavior).

        Raises ``HTTPException(403)`` on policy failure, ``HTTPException(401)``
        on an invalid token. Returns the UM response body on success
        (typically empty/200).
        """
        auth_url = f"{USER_MANAGER_URL}/v1/validate/"
        params: dict = {}
        if staff_required:
            params["staff_required"] = "true"
        if permissions_required:
            params["permissions_required"] = ",".join(permissions_required)

        return await self._request(method="GET", url=auth_url, params=params, clean_output=True)

    async def get_current_user_info(self):
        user_info_url = f"{USER_MANAGER_URL}/v1/user/info/"
        
        return await self._request(method="GET", url=user_info_url)
    
    async def get_conversation_history(self, conversation_id: str):
        conversation_url = f"{USER_MANAGER_URL}/v1/history/conversation/{conversation_id}/"
        
        return await self._request(method="GET", url=conversation_url)
        
    async def get_branch_history(self, interaction_id: str):
        interaction_url = f"{USER_MANAGER_URL}/v1/history/conversation/{interaction_id}/branch/"

        return await self._request(method="GET", url=interaction_url)
    
    async def add_interaction_message(self, interaction_id: str, message: UMMessage):
        interaction_url = f"{USER_MANAGER_URL}/v1/history/conversation/add-message/"

        payload = {
            "interaction_id": interaction_id,
            "type": message.type,
            "content": message.content,
            "steps": message.steps,
            "metadata": message.metadata
        }

        return await self._request(method="POST", url=interaction_url, json=payload)
        
    async def add_interaction(self,
                            message:UMMessage,
                            conversation_id:Optional[str] = None,
                            parent_interaction_id:Optional[str] = None,
                            title:Optional[str] = None,
                            ):
        chat_url = f"{USER_MANAGER_URL}/v1/history/conversation/"

        payload = {"messages":[message.model_dump()]}
        
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if parent_interaction_id is not None:
            payload["parent_interaction"] = parent_interaction_id # que alguien me explique porq este no tiene id ._. // Porque no todos tienen ocd como vos' id = _id nmw
        if title is not None:
            payload["title"] = title
        
        return await self._request(method="POST", url=chat_url, json=payload)
        
    async def patch_interaction(self, interaction_id:str, json:dict):
        interaction_url = f"{USER_MANAGER_URL}/v1/interaction/{interaction_id}/"
        
        return await self._request(method="PATCH", url=interaction_url, json=json)
        
    async def patch_conversation(self, conversation_id:str, json:dict):
        conversation_url = f"{USER_MANAGER_URL}/v1/history/conversation/{conversation_id}/"

        return await self._request(method="PATCH", url=conversation_url, json=json)
        
    async def patch_message(self, message_id:str, json:dict):
        message_url = f"{USER_MANAGER_URL}/v1/messages/{message_id}/"
        
        return await self._request(method="PUT", url=message_url, json=json)
        
    async def add_tag(self, tag: str):
        tag_url = f"{USER_MANAGER_URL}/v1/tags/"
        
        return await self._request(method="POST", url=tag_url, params={"tag":tag})
        
    async def get_tags(self):
        tag_url = f"{USER_MANAGER_URL}/v1/tags/"
        
        return await self._request(method="GET", url=tag_url)
        
    async def set_tags(self, conversation_id:str, tags_ids:List[str]):
        url = f"{USER_MANAGER_URL}/v1/history/conversation/{conversation_id}/set-tags/"

        return await self._request(method="POST", url=url, params={"tags":tags_ids})

    async def fetch_idp_role(self, email: str):
        url = f"{USER_MANAGER_URL}/v1/invitation/fetch-idp-role/"
        return await self._request(method="POST", url=url, json={"email": email})
    
    async def ping_credentials(self, service: str | None = None):
        ping_url = f"{USER_MANAGER_URL}/v1/credentials/ping/"
        params = {"service": service} if service else None
        return await self._request(method="POST", url=ping_url, params=params)

    async def register_permissions(self, service: str, permissions: list[dict]):
        if not self.api_key:
            raise ValueError("register_permissions requires api_key auth")
        url = f"{USER_MANAGER_URL}/v1/permissions"
        return await self._request(
            method="POST",
            url=url,
            json={"service": service, "permissions": permissions},
        )

    async def create_activity_log(self, action: str, severity: Literal["info", "warning", "error"], description: str):
        url = f"{USER_MANAGER_URL}/v1/log/"
        return await self._request(
            method="POST",
            url=url,
            json={"action": action, "severity": severity, "description": description},
        )

    # === Telemetry: Traces ===

    async def create_trace(self, trace: UMTrace):
        url = f"{USER_MANAGER_URL}/v1/traces/"
        return await self._request(method="POST", url=url, json=trace.model_dump(exclude_none=True))

    async def list_traces(self, **filters):
        """List traces. Supported filters: type, provider, model, user_id, username,
        agent_name, trace_group_id, has_error, created_at_after, created_at_before,
        search, ordering, page, page_size."""
        url = f"{USER_MANAGER_URL}/v1/traces/"
        params = {k: v for k, v in filters.items() if v is not None}
        return await self._request(method="GET", url=url, params=params)

    async def get_trace(self, trace_id: str):
        url = f"{USER_MANAGER_URL}/v1/traces/{trace_id}/"
        return await self._request(method="GET", url=url)

    # === Telemetry: Trace Groups ===

    async def create_trace_group(self, group: UMTraceGroup):
        url = f"{USER_MANAGER_URL}/v1/traces-groups/"
        return await self._request(method="POST", url=url, json=group.model_dump(exclude_none=True))

    async def list_trace_groups(self, **filters):
        """List trace groups. Supported filters: conversation_id, user_id, username,
        status, created_at_after, created_at_before, ordering, page, page_size."""
        url = f"{USER_MANAGER_URL}/v1/traces-groups/"
        params = {k: v for k, v in filters.items() if v is not None}
        return await self._request(method="GET", url=url, params=params)

    async def get_trace_group(self, group_id: str):
        url = f"{USER_MANAGER_URL}/v1/traces-groups/{group_id}/"
        return await self._request(method="GET", url=url)

    async def flush_trace_group(self, group: UMTraceGroup, traces: list[UMTrace] | None = None):
        """Upsert a trace group (by id) and bulk-insert its traces in one atomic call.
        Used by the engine at flow end. Omit/empty `traces` for a group-only upsert."""
        url = f"{USER_MANAGER_URL}/v1/traces-groups/flush/"
        payload = {
            "group": group.model_dump(exclude_none=True),
            "traces": [t.model_dump(exclude_none=True) for t in (traces or [])],
        }
        return await self._request(method="POST", url=url, json=payload)

    # === Exports ===

    async def create_export(self, export: UMExport):
        url = f"{USER_MANAGER_URL}/v1/exports/"
        return await self._request(method="POST", url=url, json=export.model_dump(exclude_none=True))

    async def list_exports(self, **filters):
        """List exports. Supported filters: source_type, source_id, mime_type,
        filename, user_id, username, mine, created_at_after, created_at_before,
        search, ordering, page, page_size."""
        url = f"{USER_MANAGER_URL}/v1/exports/"
        params = {k: v for k, v in filters.items() if v is not None}
        return await self._request(method="GET", url=url, params=params)

    async def get_export(self, export_id: str):
        url = f"{USER_MANAGER_URL}/v1/exports/{export_id}/"
        return await self._request(method="GET", url=url)

    async def list_my_exports(self, **filters):
        """List the authenticated user's exports (admin-status-agnostic).
        Same filters as list_exports except `mine`/`user_id`/`username` are ignored."""
        url = f"{USER_MANAGER_URL}/v1/exports/mine/"
        params = {k: v for k, v in filters.items() if v is not None}
        return await self._request(method="GET", url=url, params=params)

    # === Reports ===

    async def create_report(self, report: UMReport):
        """Create a report WITH its full section skeleton (atomic; ≥1 section required).
        Returns the detail representation including section ids."""
        url = f"{USER_MANAGER_URL}/v1/reports/"
        return await self._request(method="POST", url=url, json=report.model_dump())

    async def get_report(self, report_id: str):
        """Report detail including its sections."""
        url = f"{USER_MANAGER_URL}/v1/reports/{report_id}/"
        return await self._request(method="GET", url=url)

    async def list_reports(self, **filters):
        """List reports. Supported filters: report_type, status, author, page, page_size."""
        url = f"{USER_MANAGER_URL}/v1/reports/"
        params = {k: v for k, v in filters.items() if v is not None}
        return await self._request(method="GET", url=url, params=params)

    async def update_report(self, report_id: str, json: dict):
        """Patch title/report_type/metadata (status transitions are workflow, not CRUD)."""
        url = f"{USER_MANAGER_URL}/v1/reports/{report_id}/"
        return await self._request(method="PATCH", url=url, json=json)

    async def delete_report(self, report_id: str):
        """Soft-delete (is_active=False on the UM side)."""
        url = f"{USER_MANAGER_URL}/v1/reports/{report_id}/"
        return await self._request(method="DELETE", url=url)

    async def add_report_section(self, report_id: str, section: UMReportSection):
        """Add a section to an existing (non-finalized) report; UM records the tracing row."""
        url = f"{USER_MANAGER_URL}/v1/report-sections/"
        return await self._request(
            method="POST", url=url, json={"report": report_id, **section.model_dump()}
        )

    async def update_report_section(self, section_id: str, json: dict):
        """Patch a section (typically `content`); UM records the tracing row with the
        caller as actor (engine Api-Key → agent, user token → user)."""
        url = f"{USER_MANAGER_URL}/v1/report-sections/{section_id}/"
        return await self._request(method="PATCH", url=url, json=json)

    async def list_report_comments(self, report_id: str, **filters):
        """Comments on a report — section-anchored discussion and general notes, each with a
        `resolved` flag (filter to open ones client-side) and an optional `section` (null =
        general comment). Scoped to one report by `report_id`."""
        url = f"{USER_MANAGER_URL}/v1/report-comments/"
        params = {"report": report_id, **{k: v for k, v in filters.items() if v is not None}}
        return await self._request(method="GET", url=url, params=params)

    async def create_report_comment(self, report_id: str, body: str,
                                    section_id: str | None = None, parent_id: str | None = None):
        """Add a comment to a report — general, or anchored to a section (`section_id`), optionally
        as a reply to a top-level comment (`parent_id`). Authored as the SDK caller; UM gates
        eligibility (report author or a permitted reviewer)."""
        url = f"{USER_MANAGER_URL}/v1/report-comments/"
        payload = {"report": report_id, "body": body}
        if section_id is not None:
            payload["section"] = section_id
        if parent_id is not None:
            payload["parent"] = parent_id
        return await self._request(method="POST", url=url, json=payload)

    async def list_report_versions(self, report_id: str, **filters):
        """Report versions (submitted-for-review snapshots) — each with version_number, created_at,
        submitted_by, and nested reviews (reviewer + verdict + date). Scoped by `report_id`."""
        url = f"{USER_MANAGER_URL}/v1/report-versions/"
        params = {"report": report_id, **{k: v for k, v in filters.items() if v is not None}}
        return await self._request(method="GET", url=url, params=params)

    # === Task Scheduling ===

    async def list_task_schedules(self):
        """List task definitions visible to the caller, with their current schedule
        (if any). Non-staff users see only CATEGORY_USER tasks; staff see all."""
        url = f"{USER_MANAGER_URL}/v1/tasks/"
        return await self._request(method="GET", url=url)

    async def create_task_schedule(self, schedule: UMTaskSchedule):
        """Create a schedule for a registered task. The `task_definition` field
        must be a slug present in UM's TASK_REGISTRY (e.g. 'run_file_discovery').
        Returns 409 if a schedule already exists — use update_task_schedule instead."""
        url = f"{USER_MANAGER_URL}/v1/tasks/"
        return await self._request(method="POST", url=url, json=schedule.model_dump())

    async def update_task_schedule(self, task_name: str, crontab: UMCrontab, enabled: bool = True):
        """Update the schedule for a task already scheduled by the caller.
        task_name is the slug (TaskDefinition.name), not a numeric id."""
        url = f"{USER_MANAGER_URL}/v1/tasks/{task_name}/"
        payload = {"crontab": crontab.model_dump(), "enabled": enabled}
        return await self._request(method="PUT", url=url, json=payload)

    async def delete_task_schedule(self, task_name: str):
        """Delete the caller's schedule for a task. Admin-only for CATEGORY_APP tasks."""
        url = f"{USER_MANAGER_URL}/v1/tasks/{task_name}/"
        return await self._request(method="DELETE", url=url)