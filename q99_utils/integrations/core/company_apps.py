"""Which company OAuth app each integration runs against.

Every consumer needs this same answer for a different reason — the engine to fill a
consent, the hosts to know whose secret to blame when a provider rejects the app — so
it is declared once here instead of being retyped in each of them.
"""

from __future__ import annotations

from typing import Any, Optional

from q99_utils.enums.source import SourceEnum

APP_SOURCE_BY_SOURCE = {
    SourceEnum.googledrive: SourceEnum.google_oauth_app,
    SourceEnum.gmail: SourceEnum.google_oauth_app,
    SourceEnum.outlook: SourceEnum.microsoft_oauth_app,
    SourceEnum.teams: SourceEnum.microsoft_oauth_app,
    SourceEnum.sharepoint: SourceEnum.microsoft_oauth_app,
    SourceEnum.azure_ad: SourceEnum.microsoft_oauth_app,
}


def app_source_for(source: Any) -> Optional[SourceEnum]:
    """The company app a source runs against, or None when it brings its own."""
    try:
        return APP_SOURCE_BY_SOURCE.get(SourceEnum(str(source)))
    except ValueError:
        return None


__all__ = ["APP_SOURCE_BY_SOURCE", "app_source_for"]
