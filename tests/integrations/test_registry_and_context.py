"""Registry, execution context and the shared SQL base."""

from __future__ import annotations

import pytest

from q99_utils.integrations import (
    IntegrationConfig,
    IntegrationContext,
    InMemoryConnectionRegistry,
    SourceIntegrationInterface,
    SqlIntegrationBase,
    create_integration,
    get_integration_class,
    register_alias,
    registered_sources,
)
from q99_utils.integrations.sources import (
    DatabricksIntegration,
    GreenAPIIntegration,
    SlackIntegration,
)
from q99_utils.integrations.sources.greenapi import PROD_API_URL, SANDBOX_API_URL
from q99_utils.enums import SourceEnum

from tests.integrations.fakes import FakeDriver, FakeDriverFactory, FakeUserManagerSDK


class DummySqlIntegration(SqlIntegrationBase):
    SQL_DIALECT = "postgres"
    SQL_BACKEND = "postgres"


# ── registry ─────────────────────────────────────────────────────────


def test_decorator_registers_every_declared_source():
    registry = registered_sources()
    assert registry["slack"] is SlackIntegration
    assert registry["databricks"] is DatabricksIntegration
    # One class, two sources.
    assert registry["greenapi"] is GreenAPIIntegration
    assert registry["greenapi-partner"] is GreenAPIIntegration


def test_create_integration_returns_none_for_unregistered_source():
    # LLM providers and webpages have no integration class; callers rely on None.
    assert create_integration(SourceEnum.openai, um_sdk=None) is None
    assert get_integration_class("nope") is None


def test_register_alias_binds_a_runtime_name():
    register_alias("my-deployment-bucket", SlackIntegration)
    assert get_integration_class("my-deployment-bucket") is SlackIntegration


def test_create_integration_wires_source_sdk_and_context():
    sdk = FakeUserManagerSDK()
    ctx = IntegrationContext()
    integration = create_integration(SourceEnum.slack, um_sdk=sdk, context=ctx)

    assert isinstance(integration, SlackIntegration)
    assert integration.um_sdk is sdk
    assert integration.context is ctx


def test_integration_builds_without_a_context():
    # Sources needing nothing from the host must stay ceremony-free.
    integration = create_integration(SourceEnum.slack, um_sdk=None)
    assert isinstance(integration.context, IntegrationContext)
    assert integration.config.environment == "local"


# ── config ───────────────────────────────────────────────────────────


def test_greenapi_url_follows_injected_environment():
    prod = GreenAPIIntegration(
        source=SourceEnum.greenapi,
        um_sdk=None,
        context=IntegrationContext(config=IntegrationConfig(environment="prod")),
    )
    dev = GreenAPIIntegration(
        source=SourceEnum.greenapi,
        um_sdk=None,
        context=IntegrationContext(config=IntegrationConfig(environment="dev")),
    )

    assert prod.api_url == PROD_API_URL
    assert dev.api_url == SANDBOX_API_URL
    assert prod.api_url != dev.api_url


# ── connection registry ──────────────────────────────────────────────


def test_in_memory_registry_round_trip():
    registry = InMemoryConnectionRegistry()
    driver = FakeDriver()

    assert registry.get("k") is None
    registry.set("k", driver)
    assert registry.get("k") is driver
    assert registry.pop("k") is driver
    assert registry.pop("k") is None  # popping twice must not raise


# ── SQL base ─────────────────────────────────────────────────────────


def _sql_integration(factory: FakeDriverFactory | None = None) -> DummySqlIntegration:
    integration = DummySqlIntegration(
        source=SourceEnum.postgres,
        um_sdk=FakeUserManagerSDK(),
        context=IntegrationContext(driver_factory=factory or FakeDriverFactory()),
    )
    integration.credential_id = "cred-1"
    return integration


async def test_set_live_conn_builds_once_and_caches():
    factory = FakeDriverFactory()
    integration = _sql_integration(factory)

    first = await integration.set_live_conn()
    second = await integration.set_live_conn()

    assert first is second
    assert len(factory.calls) == 1, "driver must be built once per credential"


async def test_connections_are_keyed_per_credential():
    factory = FakeDriverFactory()
    integration = _sql_integration(factory)

    first = await integration.set_live_conn()
    integration.credential_id = "cred-2"
    second = await integration.set_live_conn()

    assert first is not second
    assert len(factory.calls) == 2


async def test_explicit_connection_key_overrides_credential_id():
    factory = FakeDriverFactory()
    integration = _sql_integration(factory)

    default = await integration.set_live_conn()
    scoped = await integration.set_live_conn(connection_key="other")

    assert default is not scoped
    assert integration.context.connections.get("other") is scoped


async def test_close_connection_closes_and_evicts():
    integration = _sql_integration()
    driver = await integration.set_live_conn()

    await integration.close_connection()

    assert driver.closed is True
    assert integration.context.connections.get("cred-1") is None


async def test_close_connection_is_a_noop_when_nothing_is_cached():
    integration = _sql_integration()
    await integration.close_connection()  # must not raise


async def test_set_live_conn_without_factory_fails_loudly():
    integration = DummySqlIntegration(source=SourceEnum.postgres, um_sdk=FakeUserManagerSDK())
    integration.credential_id = "cred-1"

    with pytest.raises(RuntimeError, match="driver_factory"):
        await integration.set_live_conn()


async def test_schema_discovery_delegates_to_the_driver():
    integration = _sql_integration()
    result = await integration.schema_discovery(tables=["a"], exclude_empty=True)
    assert result == "schema(tables=['a'], exclude_empty=True)"


async def test_dialect_requires_a_declared_value():
    class Undeclared(SqlIntegrationBase):
        pass

    assert await DummySqlIntegration(source=SourceEnum.postgres, um_sdk=None).dialect() == "postgres"
    with pytest.raises(NotImplementedError):
        await Undeclared(source=SourceEnum.postgres, um_sdk=None).dialect()


async def test_driver_is_requested_by_backend_not_by_source():
    # A facade source (OpenWells) runs on a backend integration while still
    # reporting its own source, so the factory must be keyed on SQL_BACKEND.
    factory = FakeDriverFactory()
    integration = DummySqlIntegration(
        source=SourceEnum.openwells,
        um_sdk=FakeUserManagerSDK(),
        context=IntegrationContext(driver_factory=factory),
    )
    integration.credential_id = "cred-1"

    await integration.set_live_conn()

    requested_backend, _ = factory.calls[0]
    assert requested_backend == "postgres"


async def test_set_live_conn_requires_a_declared_backend():
    class NoBackend(SqlIntegrationBase):
        SQL_DIALECT = "postgres"

    integration = NoBackend(
        source=SourceEnum.postgres,
        um_sdk=FakeUserManagerSDK(),
        context=IntegrationContext(driver_factory=FakeDriverFactory()),
    )
    integration.credential_id = "cred-1"

    with pytest.raises(NotImplementedError, match="SQL_BACKEND"):
        await integration.set_live_conn()


# ── base interface ───────────────────────────────────────────────────


async def test_get_credentials_requires_a_credential_id():
    integration = SourceIntegrationInterface(source=SourceEnum.slack, um_sdk=FakeUserManagerSDK())
    with pytest.raises(ValueError, match="credential_id"):
        await integration.get_credentials()


async def test_root_paths_override_shadows_stored_root_folders():
    sdk = FakeUserManagerSDK(
        {"id": "c", "source": SourceEnum.local_files, "root_folders": ["/stored"]}
    )
    integration = SourceIntegrationInterface(source=SourceEnum.local_files, um_sdk=sdk)
    integration.credential_id = "c"
    integration.root_paths_override = ["/scoped"]

    creds = await integration.get_credentials()

    assert creds.root_folders == ["/scoped"]


async def test_sync_cursors_default_to_empty_without_a_credential():
    integration = SourceIntegrationInterface(source=SourceEnum.googledrive, um_sdk=FakeUserManagerSDK())
    assert await integration.load_sync_cursors() == {}

    # Saving without a credential id must be a no-op, not a crash.
    await integration.save_sync_state({"delta": "x"})


async def test_save_sync_state_stamps_last_sync():
    sdk = FakeUserManagerSDK()
    integration = SourceIntegrationInterface(source=SourceEnum.googledrive, um_sdk=sdk)
    integration.credential_id = "cred-1"

    await integration.save_sync_state({"delta": "abc"})

    (credential_id, cursors, last_sync) = sdk.sync_state_calls[0]
    assert credential_id == "cred-1"
    assert cursors == {"delta": "abc"}
    assert last_sync  # ISO timestamp
