from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# -----------------------------
# Utils
# -----------------------------

def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + eps)


def _b64_encode_ndarray(a: np.ndarray) -> str:
    if not a.flags["C_CONTIGUOUS"]:
        a = np.ascontiguousarray(a)
    return base64.b64encode(a.tobytes()).decode("ascii")


# -----------------------------
# Model pool (on-demand load)
# -----------------------------

@dataclass
class LoadedModel:
    name: str
    max_seq_length: int
    dim: int
    model: Any  # SentenceTransformer


class ModelPool:
    def __init__(self):
        self._cache: Dict[str, LoadedModel] = {}

    def loaded_models(self) -> List[str]:
        return sorted(self._cache.keys())

    def get_or_load(self, model_name: str, max_seq_length: int) -> LoadedModel:
        key = f"{model_name}::maxlen={int(max_seq_length)}"
        if key in self._cache:
            return self._cache[key]

        # Lazy import: il server è l’unico posto dove importiamo roba pesante
        from sentence_transformers import SentenceTransformer

        m = SentenceTransformer(model_name, trust_remote_code=True)
        m.max_seq_length = int(max_seq_length)
        dim = int(m.get_sentence_embedding_dimension())

        loaded = LoadedModel(
            name=model_name,
            max_seq_length=int(max_seq_length),
            dim=dim,
            model=m,
        )
        self._cache[key] = loaded
        return loaded


POOL = ModelPool()
app = FastAPI(title="rag-embedding-server", version="0.1.0")


# -----------------------------
# API schema
# -----------------------------

class EmbedRequest(BaseModel):
    model: str
    texts: List[str]
    max_seq_length: int = 1024
    normalize: bool = True
    dtype: str = "float32"  # "float32" or "float16"
    show_progress: bool = False


class EmbedResponse(BaseModel):
    model: str
    dim: int
    dtype: str
    shape: List[int]
    data_b64: str


@app.get("/health")
def health():
    return {"ok": True, "loaded": POOL.loaded_models()}


@app.get("/models")
def models():
    return {"loaded": POOL.loaded_models()}


@app.post("/warmup")
def warmup(req: EmbedRequest):
    loaded = POOL.get_or_load(req.model, req.max_seq_length)
    # micro-warmup
    _ = loaded.model.encode(["warmup"], convert_to_numpy=True, show_progress_bar=False)
    return {"ok": True, "model": loaded.name, "dim": loaded.dim, "loaded": POOL.loaded_models()}


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts must be non-empty")

    loaded = POOL.get_or_load(req.model, req.max_seq_length)

    v = loaded.model.encode(
        req.texts,
        convert_to_numpy=True,
        show_progress_bar=bool(req.show_progress),
    ).astype("float32")

    if v.ndim == 1:
        v = v.reshape(1, -1)

    if bool(req.normalize):
        v = l2_normalize(v)

    if req.dtype not in ("float32", "float16"):
        raise HTTPException(status_code=400, detail="dtype must be float32 or float16")

    out = v.astype(req.dtype, copy=False)
    return EmbedResponse(
        model=req.model,
        dim=int(out.shape[1]),
        dtype=req.dtype,
        shape=[int(out.shape[0]), int(out.shape[1])],
        data_b64=_b64_encode_ndarray(out),
    )
