"""Reading Google's answer when a connection stops working.

Its SDK flattens a revoked grant and a bad minute into the same ``RefreshError``.
The difference is in the payload, and this is the one place that reads it.
"""

from __future__ import annotations

from typing import Any, NoReturn

from q99_utils.integrations.core.exceptions import AppCredentialExpired, CredentialExpired
from q99_utils.logger import get_logger

logger = get_logger(__name__)

INVALID_GRANT = "invalid_grant"
INVALID_CLIENT = "invalid_client"

_RECONNECT_MESSAGE = (
    "Google no longer accepts this connection. Reconnect the integration to grant "
    "access again."
)

_APP_REJECTED_MESSAGE = (
    "Google rejected the company Google application. Its client secret was rotated "
    "or expired, and an administrator has to update it."
)


def _mentions(error: BaseException, code: str) -> bool:
    """Both shapes: Google sends the parsed body when it answers JSON, text when not."""
    for arg in getattr(error, "args", ()):
        if isinstance(arg, dict) and arg.get("error") == code:
            return True
        if isinstance(arg, str) and code in arg:
            return True
    return False


def translate_refresh_error(error: BaseException, *, source: Any) -> NoReturn:
    """Sort a dead grant from a dead app; re-raise anything else untouched.

    The app is checked first: a request carrying a rejected client never gets far
    enough for the grant to be judged, and the two need opposite answers.
    """
    if _mentions(error, INVALID_CLIENT):
        logger.warning("Google rejected the company app while refreshing %s", source)
        raise AppCredentialExpired(_APP_REJECTED_MESSAGE, source=str(source)) from error
    if _mentions(error, INVALID_GRANT):
        logger.warning("Google rejected the stored grant for %s", source)
        raise CredentialExpired(_RECONNECT_MESSAGE, source=str(source)) from error
    raise error


__all__ = ["INVALID_CLIENT", "INVALID_GRANT", "translate_refresh_error"]
