"""Databricks — SQL over the Statements REST API, so it holds no driver."""

from __future__ import annotations

import re

import httpx

from q99_utils.integrations.core import SourceIntegrationInterface, register
from q99_utils.enums import SourceEnum


@register(SourceEnum.databricks)
class DatabricksIntegration(SourceIntegrationInterface):
    """Databricks SQL integration via the SQL Statements API.

    Expected credential fields
    --------------------------
    host    : Databricks workspace URL (e.g. https://<workspace>.cloud.databricks.com)
    api_key : Personal-access token (PAT)
    url     : SQL warehouse identifier (id or /sql/1.0/warehouses/<id>)
    """

    # Helpers

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        v = (value or "").strip().lower()
        return v.startswith("http://") or v.startswith("https://") or ".databricks." in v

    async def _get_runtime_credentials(self) -> dict:
        if isinstance(getattr(self, "credentials", None), dict) and self.credentials:
            return self.credentials

        await self.get_credentials()
        if not isinstance(getattr(self, "credentials", None), dict):
            raise ValueError("Databricks credentials are missing or invalid")
        return self.credentials

    async def _get_workspace_and_token(self) -> tuple[str, str]:
        creds = await self._get_runtime_credentials()
        host = (creds.get("host") or "").strip()
        token = (creds.get("api_key") or "").strip()

        if not host or not token:
            raise ValueError(
                "Databricks credentials must include 'host' (workspace URL) "
                "and 'api_key' (PAT token)."
            )

        if not host.startswith("http://") and not host.startswith("https://"):
            host = f"https://{host}"
        return host.rstrip("/"), token

    @staticmethod
    def _extract_warehouse_id(raw_value: str) -> str:
        value = (raw_value or "").strip().rstrip("/")
        if not value:
            return ""

        marker = "/sql/1.0/warehouses/"
        if marker in value:
            return value.split(marker, 1)[1].split("/", 1)[0].strip()

        if "/warehouses/" in value:
            return value.split("/warehouses/", 1)[1].split("/", 1)[0].strip()

        if value.startswith("http://") or value.startswith("https://"):
            return ""

        if "/" in value:
            candidate = value.split("/")[-1].strip()
            return candidate

        if re.fullmatch(r"[A-Za-z0-9\-]+", value):
            return value

        return ""

    # SQL execution

    async def _execute_sql(self, statement: str) -> list[dict]:
        host, token = await self._get_workspace_and_token()
        creds = await self._get_runtime_credentials()
        raw_warehouse = (creds.get("url") or "").strip()
        warehouse_id = self._extract_warehouse_id(str(raw_warehouse))
        if not warehouse_id:
            raise ValueError(
                "Databricks SQL requires a valid warehouse id in 'url', "
                "e.g. '<warehouse-id>' or '/sql/1.0/warehouses/<warehouse-id>'."
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "statement": statement,
            "warehouse_id": warehouse_id,
            "wait_timeout": "30s",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{host}/api/2.0/sql/statements",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            state = ((data.get("status") or {}).get("state") or "").upper()
            statement_id = data.get("statement_id")

            while state in {"PENDING", "RUNNING"} and statement_id:
                poll = await client.get(
                    f"{host}/api/2.0/sql/statements/{statement_id}",
                    headers=headers,
                )
                poll.raise_for_status()
                data = poll.json()
                state = ((data.get("status") or {}).get("state") or "").upper()

            if state not in {"SUCCEEDED", ""}:
                raise ValueError(f"Databricks SQL statement failed with state={state}")

            manifest = (data.get("manifest") or {}).get("schema") or {}
            cols = [c.get("name") for c in manifest.get("columns") or []]
            rows = ((data.get("result") or {}).get("data_array")) or []

            if not cols:
                return []

            output: list[dict] = []
            for row in rows:
                output.append({cols[idx]: row[idx] for idx in range(min(len(cols), len(row)))})
            return output

    # Public interface

    async def test_connection(self) -> None:
        await self._execute_sql("SELECT 1 AS ok")

    async def schema_discovery(self, tables: list[str] | None = None, exclude_empty: bool = False) -> str:
        rows = await self._execute_sql(
            """
            SELECT table_catalog, table_schema, table_name
            FROM system.information_schema.tables
            WHERE table_schema NOT IN ('information_schema')
              AND table_catalog NOT IN ('system', 'samples')
            ORDER BY table_catalog, table_schema, table_name
            LIMIT 1000
            """
        )
        if tables:
            allow = {t.lower() for t in tables}
            rows = [r for r in rows if str(r.get("table_name", "")).lower() in allow]

        lines = [
            f"{r.get('table_catalog')}.{r.get('table_schema')}.{r.get('table_name')}"
            for r in rows
        ]
        return "\n".join(lines)

    async def dialect(self) -> str:
        return "databricks"


__all__ = ["DatabricksIntegration"]
