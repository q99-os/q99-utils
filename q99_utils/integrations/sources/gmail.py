"""Gmail integration — sending mail through the Gmail API.

Gmail takes a whole RFC-2822 message base64-encoded, so unlike Outlook there is
no JSON payload to build: the work is assembling the MIME tree. Google's SDK is
an optional dependency, installed with the ``google`` extra.
"""

from __future__ import annotations

import base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Iterable, Optional, Sequence

from q99_utils.integrations.core import SourceIntegrationInterface, register
from q99_utils.enums import SourceEnum
from q99_utils.logger import get_logger
from q99_utils.models import OnboardingData

logger = get_logger(__name__)

GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

SEND_AS_AUTHENTICATED_USER = "me"


def header_join(addresses: Optional[Iterable[str]]) -> str:
    """Addresses as a single header value."""
    return ", ".join(a for a in (addresses or []) if a)


def build_raw_message(
    *,
    subject: str,
    html: str,
    to: Sequence[str],
    cc: Optional[Sequence[str]] = None,
    bcc: Optional[Sequence[str]] = None,
    attachments: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """A base64url-encoded MIME message, the only thing Gmail's send accepts.

    Attachments are the same dicts Outlook takes — ``name``, ``content_b64``
    and an optional ``content_type`` — so a caller can hand the same list to
    either provider.
    """
    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["To"] = header_join(to)
    if cc:
        root["Cc"] = header_join(cc)
    if bcc:
        root["Bcc"] = header_join(bcc)

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(html, "html", "utf-8"))
    root.attach(body)

    for attachment in attachments or []:
        content = base64.b64decode(attachment["content_b64"])
        part = MIMEApplication(content)
        part.add_header("Content-Disposition", "attachment", filename=attachment["name"])
        root.attach(part)

    return base64.urlsafe_b64encode(root.as_bytes()).decode("ascii")


def build_gmail_service(
    *,
    access_token: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
):
    """A Gmail API client that refreshes itself.

    Requires the ``google`` extra: ``pip install q99-utils[google]``.
    """
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Gmail needs Google's SDK — install q99-utils[google]"
        ) from exc

    missing = [
        name
        for name, value in (
            ("access_token", access_token),
            ("refresh_token", refresh_token),
            ("client_id", client_id),
            ("client_secret", client_secret),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Gmail credentials incomplete, missing: {', '.join(missing)}")

    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=GMAIL_TOKEN_URI,
        scopes=[GMAIL_COMPOSE_SCOPE],
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


@register(SourceEnum.gmail)
class GmailIntegration(SourceIntegrationInterface):

    async def service(self, data: Optional[OnboardingData] = None):
        credentials = await self.with_company_app(data or await self.get_credentials())
        return build_gmail_service(
            access_token=credentials.api_key,
            refresh_token=credentials.refresh_token,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
        )


__all__ = [
    "GMAIL_COMPOSE_SCOPE",
    "GMAIL_TOKEN_URI",
    "SEND_AS_AUTHENTICATED_USER",
    "GmailIntegration",
    "build_gmail_service",
    "build_raw_message",
    "header_join",
]
