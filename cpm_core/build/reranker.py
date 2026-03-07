"""Cross-encoder reranker for CPM hybrid retrieval (Phase 1)."""

from __future__ import annotations

from cpm_core.api import cpmreranker

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_cross_encoder_instance: object | None = None
_cross_encoder_model_name: str | None = None


def _get_cross_encoder(model_name: str):
    global _cross_encoder_instance, _cross_encoder_model_name
    if _cross_encoder_instance is None or _cross_encoder_model_name != model_name:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for the cross-encoder reranker. "
                "Install it with: pip install 'sentence-transformers>=2.7'"
            ) from exc
        _cross_encoder_instance = CrossEncoder(model_name)
        _cross_encoder_model_name = model_name
    return _cross_encoder_instance


@cpmreranker(name="cross-encoder", group="cpm")
class CrossEncoderReranker:
    """Reranker that uses a cross-encoder model to rescore retrieval hits.

    Implements the ``RetrievalReranker`` protocol expected by ``query.py``:
    ``rerank(*, query: str, hits: list[dict], k: int) -> list[dict]``
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self.model_name = model_name

    def rerank(self, *, query: str, hits: list[dict], k: int) -> list[dict]:
        if not hits:
            return hits
        ce = _get_cross_encoder(self.model_name)
        pairs = [(query, h.get("text", "")) for h in hits]
        scores = ce.predict(pairs)
        ranked = sorted(zip(scores, hits), key=lambda x: float(x[0]), reverse=True)
        result = []
        for score, hit in ranked[:k]:
            h = dict(hit)
            h["rerank_score"] = float(score)
            result.append(h)
        return result
