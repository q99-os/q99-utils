"""Source to integration-class registry.

Integrations register themselves with :func:`register`; the host just asks for
one instead of maintaining a lookup dict by hand.
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from q99_utils.integrations.base import SourceIntegrationInterface
from q99_utils.integrations.context import IntegrationContext
from q99_utils.models import SourceEnum
from q99_utils.um_sdk import UserManagerSDK

_REGISTRY: Dict[str, Type[SourceIntegrationInterface]] = {}


def register(*sources: SourceEnum | str):
    """Bind an integration to one or more sources.

    Varargs because s3/blob/gcs all share the bucket integration.
    """

    def decorator(cls: Type[SourceIntegrationInterface]) -> Type[SourceIntegrationInterface]:
        for source in sources:
            _REGISTRY[str(source)] = cls
        return cls

    return decorator


def register_alias(name: str, cls: Type[SourceIntegrationInterface]) -> None:
    """Bind a runtime-known name that isn't a ``SourceEnum`` member.

    Needed for deployment-dependent keys like the host's own bucket.
    """
    _REGISTRY[str(name)] = cls


def get_integration_class(
    source: SourceEnum | str,
) -> Optional[Type[SourceIntegrationInterface]]:
    """Return the class registered for *source*, or None if there is none."""
    return _REGISTRY.get(str(source))


def create_integration(
    source: SourceEnum | str,
    um_sdk: UserManagerSDK,
    context: Optional[IntegrationContext] = None,
) -> Optional[SourceIntegrationInterface]:
    """Build the integration registered for *source*, or None.

    LLM providers and webpages have no integration class; callers already treat
    that as a valid state.
    """
    cls = get_integration_class(source)
    if cls is None:
        return None
    return cls(source=source, um_sdk=um_sdk, context=context)


def registered_sources() -> Dict[str, Type[SourceIntegrationInterface]]:
    """Snapshot of the registry — for diagnostics and tests."""
    return dict(_REGISTRY)


__all__ = [
    "register",
    "register_alias",
    "get_integration_class",
    "create_integration",
    "registered_sources",
]
