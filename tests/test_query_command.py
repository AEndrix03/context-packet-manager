import json
import sys
from pathlib import Path

import faiss
import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "cpm" / "src"))

from cli.commands.query import FaissRetriever, QueryCommand, RetrievalResult


class _DummyEmbedder:
    def __init__(self, base_url: str, vector: np.ndarray):
        self.base_url = base_url
        self._vector = vector

    def health(self) -> bool:
        return True

    def embed_texts(
        self,
        texts,
        *,
        model_name: str,
        max_seq_length: int,
        normalize: bool,
        dtype: str,
        show_progress: bool,
    ) -> np.ndarray:
        return np.array([self._vector], dtype=np.float32)


def test_faiss_retriever_orders_results(tmp_path: Path) -> None:
    packet_dir = tmp_path / "packet"
    packet_dir.mkdir()
    manifest = {
        "name": "test",
        "version": "0.1.0",
        "embedding": {"model": "test-model", "max_seq_length": 16},
    }
    (packet_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    docs = [
        {"id": "first", "text": "first doc", "metadata": {"path": "a"}},
        {"id": "second", "text": "second doc", "metadata": {"path": "b"}},
    ]
    docs_path = packet_dir / "docs.jsonl"
    with docs_path.open("w", encoding="utf-8") as fh:
        for entry in docs:
            fh.write(json.dumps(entry) + "\n")

    faiss_dir = packet_dir / "faiss"
    faiss_dir.mkdir()
    index = faiss.IndexFlatIP(2)
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    index.add(vectors)
    faiss.write_index(index, str(faiss_dir / "index.faiss"))

    embedder = _DummyEmbedder("http://example", vectors[0])
    retriever = FaissRetriever(
        packet_dir=packet_dir,
        embed_url="http://example",
        embedder_factory=lambda url: embedder,
    )

    results = retriever.retrieve("query", k=2)
    assert len(results) == 2
    assert results[0].doc["id"] == "first"
    assert results[0].score > results[1].score


def test_query_command_filters_and_caches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    packet_dir = tmp_path / "packet"
    packet_dir.mkdir()

    class FakeRetriever:
        def __init__(self) -> None:
            self.model_name = "m"
            self.max_seq_length = 8

        def retrieve(self, query: str, k: int) -> list[RetrievalResult]:
            return [
                RetrievalResult(
                    score=0.9,
                    doc={"id": "keep", "text": "keep", "metadata": {"chunker": "python"}},
                    faiss_idx=0,
                ),
                RetrievalResult(
                    score=0.5,
                    doc={"id": "drop", "text": "drop", "metadata": {"chunker": "js"}},
                    faiss_idx=1,
                ),
            ][:k]

    retriever_factory = lambda packet_dir, embed_url: FakeRetriever()
    command = QueryCommand(
        cpm_dir=tmp_path,
        packet=str(packet_dir),
        query="q",
        k=2,
        metadata_filters=(("chunker", "python"),),
        use_cache=True,
        cache_refresh=False,
        retriever_factory=retriever_factory,
    )

    command.execute()
    first = capsys.readouterr().out
    assert "[cpm:query][cache-hit]" not in first
    assert "id=keep" in first

    history_dir = packet_dir / ".history" / "v1"
    assert history_dir.exists()
    entries = list(history_dir.iterdir())
    assert entries
    record_path = entries[0]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["command"]["metadata_filters"] == [{"key": "chunker", "value": "python"}]
    assert record["payload"]["results"][0]["doc"]["id"] == "keep"

    command.execute()
    second = capsys.readouterr().out
    assert "[cpm:query][cache-hit]" in second
