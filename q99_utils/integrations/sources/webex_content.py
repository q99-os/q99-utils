"""Small, predictable gate before Webex content enters document ingestion.

The document pipeline owns extraction and chunking. This module only rejects
content that cannot be useful there and removes transport noise from transcripts.
It deliberately does not use an LLM to decide whether a document matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath


MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024
MIN_TRANSCRIPT_CHARACTERS = 40

SUPPORTED_SUFFIXES = frozenset({
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".csv", ".txt", ".md", ".html", ".htm",
})
NOISE_FILENAMES = frozenset({"thumbs.db", ".ds_store", "desktop.ini"})
_VTT_CUE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[.,]\d{3}.*$")


@dataclass(frozen=True)
class ContentDecision:
    accepted: bool
    reason: str


def attachment_decision(name: str, size: int | None, content_type: str | None) -> ContentDecision:
    """Filter by metadata only; the ingestion parser validates the actual bytes."""
    filename = PurePath(name.replace("\\", "/")).name.lower().strip()
    if not filename or filename in NOISE_FILENAMES or filename.startswith("~$"):
        return ContentDecision(False, "temporary_or_system_file")
    if PurePath(filename).suffix not in SUPPORTED_SUFFIXES:
        return ContentDecision(False, "unsupported_format")
    if size is not None and (size <= 0 or size > MAX_ATTACHMENT_BYTES):
        return ContentDecision(False, "empty_or_oversized")
    if content_type and content_type.split(";", 1)[0].strip().lower() in {
        "application/x-msdownload", "application/x-executable",
    }:
        return ContentDecision(False, "executable_content")
    return ContentDecision(True, "accepted")


def clean_transcript(raw: str) -> str:
    """Remove VTT timing/cue boilerplate and adjacent repeated lines.

    Speaker labels and spoken content are preserved. Non-adjacent repetition
    may be meaningful and is therefore retained.
    """
    lines: list[str] = []
    previous = ""
    for source_line in raw.lstrip("\ufeff").replace("\x00", "").splitlines():
        line = " ".join(source_line.split())
        if not line or line == "WEBVTT" or line.isdecimal() or _VTT_CUE.fullmatch(line):
            continue
        if line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def transcript_decision(raw: str) -> tuple[ContentDecision, str]:
    if len(raw.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
        return ContentDecision(False, "oversized"), ""
    cleaned = clean_transcript(raw)
    if len(cleaned.strip()) < MIN_TRANSCRIPT_CHARACTERS:
        return ContentDecision(False, "empty_or_too_short"), ""
    return ContentDecision(True, "accepted"), cleaned
