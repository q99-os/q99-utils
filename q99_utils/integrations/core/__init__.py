"""The machinery every integration is built on. Concrete ones live in sources/."""

from q99_utils.integrations.core.change_detection import classify_change
from q99_utils.integrations.core.company_apps import APP_SOURCE_BY_SOURCE, app_source_for
from q99_utils.integrations.core.context import IntegrationConfig, IntegrationContext
from q99_utils.integrations.core.google_oauth import translate_refresh_error
from q99_utils.integrations.core.exceptions import (
    AppCredentialExpired,
    CredentialExpired,
    CredentialValidationError,
    IntegrationError,
    ResourceNotFound,
)
from q99_utils.integrations.core.microsoft_graph import (
    DELEGATED_MAIL_SCOPES,
    DELEGATED_TEAMS_SCOPES,
    DelegatedGraphClient,
    DelegatedTokenExpired,
    GRAPH_BASE_URL,
    GRAPH_SCOPE,
    MicrosoftGraphAuth,
    acquire_graph_token,
    graph_paginate,
    graph_request,
    refresh_delegated_token,
    request_graph_token,
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
    "APP_SOURCE_BY_SOURCE",
    "AppCredentialExpired",
    "CredentialExpired",
    "app_source_for",
    "translate_refresh_error",
    "CredentialValidationError",
    "DELEGATED_MAIL_SCOPES",
    "DELEGATED_TEAMS_SCOPES",
    "DelegatedGraphClient",
    "DelegatedTokenExpired",
    "GRAPH_BASE_URL",
    "GRAPH_SCOPE",
    "IntegrationConfig",
    "IntegrationContext",
    "IntegrationError",
    "MicrosoftGraphAuth",
    "ResourceNotFound",
    "SourceIntegrationInterface",
    "SqlIntegrationBase",
    "acquire_graph_token",
    "classify_change",
    "graph_paginate",
    "graph_request",
    "request_graph_token",
    "create_integration",
    "get_integration_class",
    "register",
    "register_alias",
    "registered_sources",
]
