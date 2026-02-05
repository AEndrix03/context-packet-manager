from __future__ import annotations

from pathlib import Path
from typing import Tuple

import faiss
import numpy as np


class FaissFlatIP:
    """Cosine similarity via Inner Product on L2-normalized vectors."""

    def __init__(self, dim: int):
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)

    def add(self, vectors: np.ndarray) -> None:
        if vectors.dtype != np.float32:
            vectors = vectors.astype("float32")
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(f"Expected vectors shape (n, {self.dim}), got {vectors.shape}")
        self.index.add(vectors)

    def search(self, query_vec: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        if query_vec.dtype != np.float32:
            query_vec = query_vec.astype("float32")
        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)
        scores, ids = self.index.search(query_vec, k)
        return scores[0], ids[0]

    def save(self, path: Path | str) -> None:
        faiss.write_index(self.index, str(path))


def load_faiss_index(path: Path | str) -> faiss.Index:
    return faiss.read_index(str(path))


def save_faiss_index(index: faiss.Index, path: Path | str) -> None:
    faiss.write_index(index, str(path))
