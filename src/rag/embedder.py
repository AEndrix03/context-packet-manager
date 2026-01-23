from typing import List
import numpy as np
from sentence_transformers import SentenceTransformer

def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + eps)

class JinaCodeEmbedder:
    """
    jinaai/jina-embeddings-v2-base-code (code-friendly embeddings)
    """
    def __init__(self, model_name: str = "jinaai/jina-embeddings-v2-base-code", max_seq_length: int = 1024):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, trust_remote_code=True)
        self.model.max_seq_length = max_seq_length

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not texts:
            # evita crash: ritorna matrice vuota con dim corretta
            return np.zeros((0, self.dim), dtype=np.float32)

        v = self.model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=True,
        ).astype("float32")

        # se N=1 a volte torna 1D, forziamo (1, dim)
        if v.ndim == 1:
            v = v.reshape(1, -1)

        return l2_normalize(v)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]