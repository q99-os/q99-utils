"""SQL-backed integrations.

They carry almost no code; what matters is the two values each declares, since
getting them wrong fails silently.
"""

from __future__ import annotations

import pytest

from q99_utils.integrations import IntegrationContext, create_integration
from q99_utils.integrations.sources import (
    BigQueryIntegration,
    MSSQLIntegration,
    PostgresIntegration,
)
from q99_utils.models import SourceEnum

from tests.integrations.fakes import FakeDriverFactory, FakeUserManagerSDK

# source, class, sqlglot dialect, driver backend
SQL_SOURCES = [
    (SourceEnum.postgres, PostgresIntegration, "postgres", "postgres"),
    (SourceEnum.mssql, MSSQLIntegration, "tsql", "mssql"),
    (SourceEnum.bigquery, BigQueryIntegration, "bigquery", "bigquery"),
]


@pytest.mark.parametrize("source,expected_class,dialect,backend", SQL_SOURCES)
def test_source_resolves_to_its_integration(source, expected_class, dialect, backend):
    integration = create_integration(source, um_sdk=None)
    assert isinstance(integration, expected_class)


@pytest.mark.parametrize("source,expected_class,dialect,backend", SQL_SOURCES)
async def test_declared_dialect_is_a_name_sqlglot_accepts(source, expected_class, dialect, backend):
    integration = create_integration(source, um_sdk=None)
    assert await integration.dialect() == dialect


@pytest.mark.parametrize("source,expected_class,dialect,backend", SQL_SOURCES)
async def test_requests_the_right_driver_backend(source, expected_class, dialect, backend):
    factory = FakeDriverFactory()
    integration = create_integration(
        source,
        um_sdk=FakeUserManagerSDK(),
        context=IntegrationContext(driver_factory=factory),
    )
    integration.credential_id = "cred-1"

    await integration.set_live_conn()

    assert factory.backends == [backend]


async def test_mssql_dialect_and_backend_deliberately_differ():
    # The one case where the two values are not the same string — a regression
    # here would silently send T-SQL through the wrong driver or vice versa.
    integration = create_integration(SourceEnum.mssql, um_sdk=None)
    assert await integration.dialect() == "tsql"
    assert integration.SQL_BACKEND == "mssql"


async def test_each_credential_gets_its_own_connection():
    factory = FakeDriverFactory()
    integration = create_integration(
        SourceEnum.postgres,
        um_sdk=FakeUserManagerSDK(),
        context=IntegrationContext(driver_factory=factory),
    )

    integration.credential_id = "cred-1"
    first = await integration.set_live_conn()
    integration.credential_id = "cred-2"
    second = await integration.set_live_conn()

    assert first is not second
    assert len(factory.backends) == 2
