from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import requests


@dataclass
class HttpEmbedder:
    base_url: str  # e.g. http://127.0.0.1:8765
    timeout_s: Optional[float] = None  # None = nessun timeout

    def health(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=2.0)
            return r.ok
        except Exception:
            return False

    def embed_texts(
        self,
        texts: List[str],
        *,
        model_name: str,
        max_seq_length: int = 1024,
        normalize: bool = True,
        dtype: str = "float32",
        show_progress: bool = False,
    ) -> np.ndarray:
        payload = {
            "model": model_name,
            "texts": texts,
            "options": {
                "max_seq_length": int(max_seq_length),
                "normalize": bool(normalize),
                "show_progress": bool(show_progress),
            },
        }

        r = requests.post(f"{self.base_url}/embed", json=payload, timeout=self.timeout_s)
        r.raise_for_status()
        j = r.json()
        
        # faiss vuole float32
        return np.array(j["vectors"], dtype=np.float32)