from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence


class EmbeddingCache:
    def __init__(self, cache_root: Path | str | None = None) -> None:
        base = Path(cache_root) if cache_root else Path(".cpm/cache/embeddings")
        self.cache_root = base.expanduser()
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _entry_path(self, provider: str, text: str) -> Path:
        digest = hashlib.sha256(f"{provider}|{text}".encode("utf-8")).hexdigest()
        bucket = self.cache_root / digest[:2]
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket / f"{digest}.json"

    def get(self, provider: str, text: str) -> list[float] | None:
        path = self._entry_path(provider, text)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        vector = payload.get("vector")
        if not isinstance(vector, list):
            return None
        return [float(value) for value in vector]

    def set(self, provider: str, text: str, vector: Sequence[float]) -> None:
        path = self._entry_path(provider, text)
        payload = {"vector": [float(value) for value in vector]}
        path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
