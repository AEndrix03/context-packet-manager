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

    def warmup(self, *, model_name: str, max_seq_length: int = 1024) -> bool:
        try:
            payload = {
                "model": model_name,
                "texts": ["warmup"],
                "max_seq_length": int(max_seq_length),
                "normalize": True,
                "dtype": "float32",
                "show_progress": False,
            }
            r = requests.post(f"{self.base_url}/warmup", json=payload, timeout=self.timeout_s)
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
            "max_seq_length": int(max_seq_length),
            "normalize": bool(normalize),
            "dtype": dtype,
            "show_progress": bool(show_progress),
        }

        def _do_request() -> np.ndarray:
            r = requests.post(f"{self.base_url}/embed", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            j = r.json()

            shape = tuple(j["shape"])
            dt = np.float32 if j["dtype"] == "float32" else np.float16
            raw = base64.b64decode(j["data_b64"].encode("ascii"))
            arr = np.frombuffer(raw, dtype=dt).reshape(shape)

            # faiss vuole float32
            if arr.dtype != np.float32:
                arr = arr.astype("float32")
            return arr

        try:
            return _do_request()
        except requests.exceptions.ReadTimeout:
            # tipico cold start: tenta warmup e riprova una volta
            self.warmup(model_name=model_name, max_seq_length=max_seq_length)
            return _do_request()