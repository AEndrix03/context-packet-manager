"""End-to-end validation for the built-in build command."""

from __future__ import annotations

from pathlib import Path

from cpm_cli import main as cli_main
from cpm_core.build import DefaultBuilderConfig
from cpm_core.packet.faiss_db import load_faiss_index
from cpm_core.packet.io import (
    load_manifest,
    read_docs_jsonl,
    read_vectors_f16,
)


class _FakeHealthResponse:
    ok = True


class _FakeEmbedResponse:
    def __init__(self, vectors: list[list[float]]):
        self._vectors = vectors

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, list[list[float]]]:
        return {"vectors": self._vectors}


def test_build_command_creates_packet(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("Welcome\nThis is a sample project\nEnd", encoding="utf-8")
    (project / "code.py").write_text("def hello():\n    return 42\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        "cpm_core.build.builder.requests.get", lambda *args, **kwargs: _FakeHealthResponse()
    )

    def fake_post(*args, **kwargs):
        texts = kwargs["json"]["texts"]
        dims = 4
        vectors = []
        for idx in range(len(texts)):
            vector = [1.0 if component == idx else 0.0 for component in range(dims)]
            vectors.append(vector)
        return _FakeEmbedResponse(vectors)

    monkeypatch.setattr("cpm_core.build.builder.requests.post", fake_post)

    result = cli_main(
        ["build", "--source", "docs", "--packet-version", "1.2.3"], start_dir=tmp_path
    )
    assert result == 0

    packet_dir = tmp_path / ".cpm" / "packages" / "docs"
    manifest = load_manifest(packet_dir / "manifest.json")
    assert manifest.cpm["version"] == "1.2.3"
    assert manifest.embedding.model == DefaultBuilderConfig().model_name
    assert manifest.counts["docs"] == 2
    assert manifest.counts["vectors"] == 2
    assert manifest.incremental["embedded"] == 2

    docs = read_docs_jsonl(packet_dir / "docs.jsonl")
    assert len(docs) == 2

    vectors = read_vectors_f16(packet_dir / "vectors.f16.bin", dim=manifest.embedding.dim)
    assert vectors.shape == (2, manifest.embedding.dim)

    faiss_index = load_faiss_index(packet_dir / "faiss" / "index.faiss")
    scores, ids = faiss_index.search(vectors[:1], 1)
    assert ids[0][0] == 0
