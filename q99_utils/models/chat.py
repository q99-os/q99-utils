from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class UMMessage(BaseModel):
    content: str = ""
    steps: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = {}
    type: Literal["Question", "Answer", "Interruption", "Error"]


__all__ = ["UMMessage"]
