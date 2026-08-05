from __future__ import annotations

from typing import Any, List, Optional

from q99_utils.integrations.core import SourceIntegrationInterface, get_integration_class, register
from q99_utils.logger import get_logger
from q99_utils.enums import DatabaseBackendEnum, SourceEnum

logger = get_logger(__name__)

# Known OpenWells tables - verified against live database
OPENWELLS_KNOWN_TABLES = [
    # Well master data
    "CD_WELL_SOURCE",
    "CD_DATUM_T",
    "CD_SITE_SOURCE",
    # Assembly & components
    "CD_ASSEMBLY",
    "CD_ASSEMBLY_COMP",
    "CD_BHA_COMP_BIT",
    # Activities & operations
    "DM_ACTIVITY",
    "DM_EVENT",
    "DM_WELL_PLAN_T",
    "DM_WELL_PLAN_OP",
    "DM_REPORT_JOURNAL",
    # BHA & pipe
    "DM_BHA_RUN",
    "DM_PIPE_RUN",
    "DM_PIPE_DATA",
    # Fluids & mud
    "CD_FLUID",
    "DM_MUD_PRODUCT",
    "DM_MUD_VOLUME",
    # Cement
    "CD_CEMENT_JOB",
    # Surveys
    "CD_DEFINITIVE_SURVEY_HEADER",
    "CD_DEFINITIVE_SURVEY_STATION",
    # Solids control
    "DM_HYDROCLONE_OP",
    "DM_CENTRIFUGE_OP",
    # NPT & equipment failures
    "DM_OPER_EQUIP_FAIL",
    # Costs
    "DM_DAILYCOST",
]


@register(SourceEnum.openwells)
class OpenWellsIntegration(SourceIntegrationInterface):
    """OpenWells is drilling/well management software that can be deployed on
    different databases. This integration abstracts that layer away, delegating
    to the SQL integration matching the credential's ``database_backend``.
    """

    def __init__(self, source: SourceEnum, um_sdk, context=None) -> None:
        super().__init__(source, um_sdk, context=context)
        self._backend_integration: Optional[SourceIntegrationInterface] = None

    async def _get_backend_integration(self) -> SourceIntegrationInterface:
        """The SQL integration for the configured backend, built as *this* source.

        Looking the class up by backend but constructing it as 'openwells' is
        what keeps live connections and prompt fragments keyed to openwells.
        """
        if self._backend_integration is None:
            credentials = await self.get_credentials()
            backend = credentials.database_backend or DatabaseBackendEnum.mssql
            backend_source = SourceEnum(backend.value)

            backend_class = get_integration_class(backend_source)
            if backend_class is None:
                raise ValueError(f"Unsupported database backend: {backend}")

            self._backend_integration = backend_class(
                source=self.source,
                um_sdk=self.um_sdk,
                context=self.context,
            )
            if self.credential_id:
                self._backend_integration.credential_id = self.credential_id

        return self._backend_integration

    async def set_live_conn(self) -> Any:
        backend_integration = await self._get_backend_integration()
        return await backend_integration.set_live_conn()

    async def dialect(self) -> str:
        """Delegate to the resolved backend integration.

        OpenWells is a facade — the actual SQL dialect depends on
        database_backend (mssql → tsql, postgres → postgres).
        """
        backend = await self._get_backend_integration()
        return await backend.dialect()

    async def schema_discovery(self, tables: Optional[List[str]] = None) -> str:
        """Describe the schema, restricted to the known OpenWells tables.

        Scanning an entire production database we don't own is both slow and
        risky, so the table list is fixed unless a caller narrows it further.
        """
        driver = await self.set_live_conn()
        target_tables = tables or OPENWELLS_KNOWN_TABLES

        return await driver.get_schema(
            tables=target_tables,
            exclude_empty=True,
        )

    async def close_connection(self):
        """Close the backend's connection.

        A fresh instance (credential rotation) never built one, but a driver may
        still be cached under this credential_id.
        """
        if self._backend_integration:
            await self._backend_integration.close_connection()
            self._backend_integration = None
            logger.info(f"Closed OpenWells connection for '{self.source}'.")
        elif self.credential_id:
            driver = self.context.connections.pop(self.credential_id)
            if driver is not None:
                await driver.close()


__all__ = ["OpenWellsIntegration", "OPENWELLS_KNOWN_TABLES"]
