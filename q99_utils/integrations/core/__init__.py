"""The machinery every integration is built on. Concrete ones live in sources/."""

from q99_utils.integrations.core.change_detection import classify_change
from q99_utils.integrations.core.context import IntegrationConfig, IntegrationContext
from q99_utils.integrations.core.exceptions import (
    CredentialValidationError,
    IntegrationError,
)
from q99_utils.integrations.core.registry import (
    create_integration,
    get_integration_class,
    register,
    register_alias,
    registered_sources,
)
from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.integrations.core.sql_source import SqlIntegrationBase

__all__ = [
    "CredentialValidationError",
    "IntegrationConfig",
    "IntegrationContext",
    "IntegrationError",
    "SourceIntegrationInterface",
    "SqlIntegrationBase",
    "classify_change",
    "create_integration",
    "get_integration_class",
    "register",
    "register_alias",
    "registered_sources",
]
