from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass
class ChatResponse:
    content: str
    raw: Dict[str, Any]
    model: Optional[str] = None
