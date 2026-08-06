"""Framework-agnostic errors: status codes are the host's call, not a library's."""

from __future__ import annotations

from typing import Optional


class IntegrationError(Exception):
    """Base class for every error raised by a source integration."""


class CredentialValidationError(IntegrationError):
    """A credential could not be validated against its provider.

    ``message`` is safe to show an end user; the provider's raw failure belongs
    in the logs. Hosts usually map this to HTTP 422.
    """

    def __init__(self, message: str, *, source: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.source = source

    def __str__(self) -> str:
        return self.message


__all__ = ["IntegrationError", "CredentialValidationError"]
