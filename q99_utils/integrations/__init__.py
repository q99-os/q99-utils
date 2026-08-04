"""Source integrations.

Importing this package registers every concrete integration, so a host only
needs ``create_integration(source, um_sdk, context)``.
"""

from q99_utils.integrations.base import SourceIntegrationInterface
from q99_utils.integrations.context import IntegrationConfig, IntegrationContext
from q99_utils.integrations.exceptions import (
    CredentialValidationError,
    IntegrationError,
)
from q99_utils.integrations.models import (
    ChangeKind,
    DiscoveredFile,
    PermissionTokens,
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
from q99_utils.integrations.registry import (
    create_integration,
    get_integration_class,
    register,
    register_alias,
    registered_sources,
)
from q99_utils.integrations.sql_base import SqlIntegrationBase

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
    "ChangeKind",
    "DiscoveredFile",
    "discoveredFile",
    "ResourceNode",
    "PermissionTokens",
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
