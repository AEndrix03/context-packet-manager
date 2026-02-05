from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class Chunk:
    id: str
    text: str
    metadata: Dict[str, Any]
