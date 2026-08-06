"""Source integrations. Importing this package registers all of them."""

from q99_utils.integrations.core import (
    CredentialValidationError,
    IntegrationConfig,
    IntegrationContext,
    IntegrationError,
    SourceIntegrationInterface,
    SqlIntegrationBase,
    create_integration,
    get_integration_class,
    register,
    register_alias,
    registered_sources,
)
from q99_utils.integrations.mappers import OpenWellsAgentMapper, OpenWellsEDMMapper
from q99_utils.integrations.discovery import (
    ChangeKind,
    DiscoveredFile,
    ResourceNode,
    discoveredFile,
)
from q99_utils.integrations.ports import (
    ConnectionRegistry,
    FileReferenceStore,
    InMemoryConnectionRegistry,
    IndexedFile,
    ManagedBucket,
    ManagedBucketProvider,
    SqlDriver,
    SqlDriverFactory,
    StorageService,
    StorageServiceFactory,
)

# Imported for its side effect: applying @register to every concrete integration.
from q99_utils.integrations import sources as sources
from q99_utils.integrations.sources import *  # noqa: F401,F403

__all__ = [
    "SourceIntegrationInterface",
    "SqlIntegrationBase",
    "IntegrationConfig",
    "IntegrationContext",
    "IntegrationError",
    "CredentialValidationError",
    "OpenWellsAgentMapper",
    "OpenWellsEDMMapper",
    "ChangeKind",
    "DiscoveredFile",
    "discoveredFile",
    "ResourceNode",
    "ConnectionRegistry",
    "FileReferenceStore",
    "InMemoryConnectionRegistry",
    "IndexedFile",
    "ManagedBucket",
    "ManagedBucketProvider",
    "SqlDriver",
    "SqlDriverFactory",
    "StorageService",
    "StorageServiceFactory",
    "register",
    "register_alias",
    "get_integration_class",
    "create_integration",
    "registered_sources",
    *sources.__all__,
]
