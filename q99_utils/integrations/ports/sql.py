"""Ports for SQL backends."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from q99_utils.models import OnboardingData


@runtime_checkable
class SqlDriver(Protocol):
    """A live connection to a SQL backend, owned by the host.

    ``query`` is deliberately loose: the concrete drivers differ (BigQuery takes
    just the statement, Postgres/MSSQL also take params and a fetch flag).
    """

    async def query(self, sql: str, *args: Any, **kwargs: Any) -> Optional[List[Dict[str, Any]]]:
        ...

    async def get_schema(
        self,
        tables: Optional[List[str]] = None,
        exclude_empty: bool = False,
    ) -> str:
        ...

    async def close(self) -> None:
        ...


@runtime_checkable
class SqlDriverFactory(Protocol):
    """Builds an initialised :class:`SqlDriver` for a backend + credential pair.

    Keyed on ``backend`` (the integration's ``SQL_BACKEND``), not on the source:
    a facade source like OpenWells runs on the Postgres or MSSQL integration
    while still reporting itself as 'openwells', so the source does not identify
    the driver to build.
    """

    async def create(self, backend: str, credentials: OnboardingData) -> SqlDriver:
        ...


@runtime_checkable
class ConnectionRegistry(Protocol):
    """Process-wide cache of live connections, keyed by credential."""

    def get(self, key: str) -> Optional[SqlDriver]:
        ...

    def set(self, key: str, driver: SqlDriver) -> None:
        ...

    def pop(self, key: str) -> Optional[SqlDriver]:
        ...


class InMemoryConnectionRegistry:
    """Default :class:`ConnectionRegistry` — a dict.

    Enough for tests, single-process hosts, and as the fallback when a caller
    builds an integration without wiring a registry.
    """

    def __init__(self) -> None:
        self._connections: Dict[str, SqlDriver] = {}

    def get(self, key: str) -> Optional[SqlDriver]:
        return self._connections.get(key)

    def set(self, key: str, driver: SqlDriver) -> None:
        self._connections[key] = driver

    def pop(self, key: str) -> Optional[SqlDriver]:
        return self._connections.pop(key, None)


__all__ = [
    "ConnectionRegistry",
    "InMemoryConnectionRegistry",
    "SqlDriver",
    "SqlDriverFactory",
]
