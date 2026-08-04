"""Shared connect / cache / close behaviour for SQL-backed integrations.

Postgres, MSSQL and BigQuery each had their own copy of this, differing only in
which driver they built and which dialect they reported.
"""

from __future__ import annotations

from typing import List, Optional

from q99_utils.integrations.base import SourceIntegrationInterface
from q99_utils.integrations.ports import SqlDriver
from q99_utils.logger import get_logger

logger = get_logger(__name__)


class SqlIntegrationBase(SourceIntegrationInterface):
    """Base for integrations that expose a live SQL connection."""

    #: sqlglot dialect name (postgres, tsql, bigquery, databricks).
    SQL_DIALECT: str = ""

    #: Which driver the host must build for this integration. Distinct from
    #: SQL_DIALECT (MSSQL speaks 'tsql' but its driver is 'mssql') and from the
    #: source, which a facade like OpenWells overrides while still running on
    #: this class.
    SQL_BACKEND: str = ""

    def _connection_key(self, connection_key: Optional[str] = None) -> str:
        """Explicit key, then credential id, then the source name."""
        return str(connection_key or self.credential_id or self.source)

    async def set_live_conn(self, connection_key: Optional[str] = None) -> SqlDriver:
        """Return the cached driver for this credential, building it on first use."""
        key = self._connection_key(connection_key)

        driver = self.context.connections.get(key)
        if driver is not None:
            return driver

        factory = self.context.driver_factory
        if factory is None:
            raise RuntimeError(
                f"No driver_factory configured on the IntegrationContext — "
                f"'{self.source}' cannot open a SQL connection."
            )
        if not self.SQL_BACKEND:
            raise NotImplementedError(
                f"{type(self).__name__} must declare SQL_BACKEND."
            )

        credentials = await self.get_credentials()
        driver = await factory.create(self.SQL_BACKEND, credentials)
        self.context.connections.set(key, driver)
        logger.info("Live %s connection opened for key '%s'.", self.source, key)
        return driver

    async def schema_discovery(
        self,
        tables: Optional[List[str]] = None,
        exclude_empty: bool = False,
    ) -> str:
        """Return an LLM-ready description of the backend's schema."""
        driver = await self.set_live_conn()
        return await driver.get_schema(tables=tables, exclude_empty=exclude_empty)

    async def close_connection(self, connection_key: Optional[str] = None) -> None:
        """Close the cached driver and drop it from the registry.

        Evicted before awaiting ``close()``, so a driver that fails to close
        still leaves the registry consistent.
        """
        key = self._connection_key(connection_key)
        driver = self.context.connections.pop(key)
        if driver is None:
            return
        await driver.close()
        logger.info("Closed %s connection for key '%s'.", self.source, key)

    async def dialect(self) -> str:
        if not self.SQL_DIALECT:
            raise NotImplementedError(
                f"{type(self).__name__} must declare SQL_DIALECT."
            )
        return self.SQL_DIALECT


__all__ = ["SqlIntegrationBase"]
