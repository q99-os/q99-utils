"""Port for reading the OAuth app a source runs against.

The integrations cannot read it themselves: a company credential is only visible to
staff, and the SDK they are handed usually carries the token of whoever triggered the
work. The host has rights they do not, so it answers this instead.

Returning ``None`` is a normal answer, not a failure — it means "use whatever the
credential already carries", which is what every integration did before this existed.
"""

from __future__ import annotations

from typing import Mapping, Optional, Protocol, runtime_checkable


@runtime_checkable
class CompanyAppProvider(Protocol):
    """Reads the company's OAuth app with credentials a user token cannot."""

    async def app_credentials(self, app_source: str) -> Optional[Mapping[str, str]]:
        """``client_id`` / ``client_secret`` / ``tenant_id`` for that app, or None.

        Called on every token acquisition, so implementations are expected to cache.
        """
        ...


__all__ = ["CompanyAppProvider"]
