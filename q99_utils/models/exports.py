from typing import Optional

from pydantic import BaseModel


class UMExport(BaseModel):
    id: Optional[str] = None
    created_at: Optional[int] = None
    user: Optional[int] = None
    filename: str
    mime_type: str
    storage_path: str
    size_bytes: Optional[int] = None
    source_type: Optional[str] = None  # e.g., "chat_report", "extraction", "query"
    source_id: Optional[str] = None


__all__ = ["UMExport"]
