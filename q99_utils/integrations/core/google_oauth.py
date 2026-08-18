"""Reading Google's answer when a connection stops working.

Its SDK flattens a revoked grant and a bad minute into the same ``RefreshError``.
The difference is in the payload, and this is the one place that reads it.
"""

from __future__ import annotations

from typing import Any, NoReturn

from q99_utils.integrations.core.exceptions import CredentialExpired
from q99_utils.logger import get_logger

logger = get_logger(__name__)

INVALID_GRANT = "invalid_grant"

_RECONNECT_MESSAGE = (
    "Google no longer accepts this connection. Reconnect the integration to grant "
    "access again."
)


def _mentions_invalid_grant(error: BaseException) -> bool:
    """Both shapes: Google sends the parsed body when it answers JSON, text when not."""
    for arg in getattr(error, "args", ()):
        if isinstance(arg, dict) and arg.get("error") == INVALID_GRANT:
            return True
        if isinstance(arg, str) and INVALID_GRANT in arg:
            return True
    return False


def translate_refresh_error(error: BaseException, *, source: Any) -> NoReturn:
    """Raise CredentialExpired for a dead grant; re-raise anything else untouched."""
    if _mentions_invalid_grant(error):
        logger.warning("Google rejected the stored grant for %s", source)
        raise CredentialExpired(_RECONNECT_MESSAGE, source=str(source)) from error
    raise error


__all__ = ["INVALID_GRANT", "translate_refresh_error"]
