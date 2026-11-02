"""What the engine needs from a company mailbox, whatever the provider.

The engine reads new mail, downloads the attachments it keeps and then moves each
message out of the inbox, so the inbox only ever holds what is still to be read.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from q99_utils.integrations.core.source import SourceIntegrationInterface
from q99_utils.models import OnboardingData

# Folder (Outlook) or label (Gmail) that read messages are moved to.
PROCESSED_FOLDER = "Quantos Processed"


@dataclass
class MailAttachment:
    id: str
    name: str
    content_type: str
    size: int
    is_inline: bool


@dataclass
class MailMessage:
    id: str
    received_at: datetime
    attachments: List[MailAttachment] = field(default_factory=list)


class MailboxIntegration(SourceIntegrationInterface):

    @abstractmethod
    async def list_inbox_messages(self, data: OnboardingData, received_after: datetime) -> List[MailMessage]:
        """Messages in the inbox received at or after ``received_after``, with their file attachments."""

    @abstractmethod
    async def download_attachment(self, message_id: str, attachment_id: str, data: OnboardingData) -> bytes:
        """The attachment's bytes."""

    @abstractmethod
    async def mark_processed(self, message_id: str, data: OnboardingData) -> None:
        """Move the message out of the inbox into ``PROCESSED_FOLDER``, creating it if missing."""


__all__ = ["MailAttachment", "MailMessage", "MailboxIntegration", "PROCESSED_FOLDER"]
