"""End-to-end validation for the built-in build command."""

from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np

from cpm_cli import main as cli_main
from cpm_core.build import DefaultBuilderConfig
from cpm_core.packet.faiss_db import load_faiss_index
from cpm_core.packet.io import (
    load_manifest,
    read_docs_jsonl,
    read_vectors_f16,
)


def test_build_command_creates_packet(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("Welcome\nThis is a sample project\nEnd", encoding="utf-8")
    (project / "code.py").write_text("def hello():\n    return 42\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr("cpm_builtin.embeddings.client.EmbeddingClient.health", lambda self: True)

    def fake_embed_texts(
        self,
        texts,
        *,
        model_name: str,
        max_seq_length: int,
        normalize: bool,
        dtype: str,
        show_progress: bool,
    ):
        dims = 4
        vectors = []
        for idx in range(len(texts)):
            vector = [1.0 if component == idx else 0.0 for component in range(dims)]
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)

    monkeypatch.setattr(
        "cpm_builtin.embeddings.client.EmbeddingClient.embed_texts",
        fake_embed_texts,
    )

    result = cli_main(
        [
            "build",
            "run",
            "--source",
            "docs",
            "--name",
            "docs",
            "--packet-version",
            "1.2.3",
        ],
        start_dir=tmp_path,
    )
    assert result == 0

    packet_dir = tmp_path / "dist" / "docs" / "1.2.3"
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


def test_build_command_can_select_plugin_builder(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("sample", encoding="utf-8")

    plugin_src = Path("tests") / "fixtures" / "plugins" / "sample_plugin"
    plugin_dst = tmp_path / ".cpm" / "plugins" / "sample_plugin"
    plugin_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plugin_src, plugin_dst)

    monkeypatch.chdir(tmp_path)

    result = cli_main(
        [
            "build",
            "run",
            "--source",
            "docs",
            "--destination",
            str(tmp_path / "out"),
            "--name",
            "docs",
            "--packet-version",
            "0.0.1",
            "--builder",
            "sample:sample-builder",
        ],
        start_dir=tmp_path,
    )
    assert result == 0


def test_build_describe_updates_packet_metadata(tmp_path: Path) -> None:
    packet_dir = tmp_path / ".cpm" / "dist" / "docs" / "1.0.0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "cpm.yml").write_text("name: docs\nversion: 1.0.0\ndescription: old\n", encoding="utf-8")
    (packet_dir / "manifest.json").write_text(
        '{"cpm": {"name": "docs", "version": "1.0.0", "description": "old"}}',
        encoding="utf-8",
    )

    result = cli_main(
        [
            "build",
            "--workspace-dir",
            str(tmp_path),
            "describe",
            "--destination",
            "dist",
            "--name",
            "docs",
            "--packet-version",
            "1.0.0",
            "--description",
            "new description",
        ],
        start_dir=tmp_path,
    )
    assert result == 0
    assert "new description" in (packet_dir / "cpm.yml").read_text(encoding="utf-8")
    assert "new description" in (packet_dir / "manifest.json").read_text(encoding="utf-8")
