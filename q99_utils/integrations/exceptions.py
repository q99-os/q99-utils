"""Errors raised by integrations.

Framework-agnostic on purpose: deciding HTTP status codes is the host's job,
not a library's. See the README for how to map them.
"""

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
