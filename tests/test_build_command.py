"""End-to-end validation for the built-in build command."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np

from cpm_cli import main as cli_main
from cpm_core.build import DefaultBuilderConfig
from cpm_core.packet import load_lock
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


def test_build_command_generates_lockfile(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("Welcome\nThis is a sample project\nEnd", encoding="utf-8")

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

    lock_path = tmp_path / "dist" / "docs" / "1.2.3" / "packet.lock.json"
    assert lock_path.exists()
    lock_payload = load_lock(lock_path)
    assert lock_payload["packet"]["name"] == "docs"
    assert lock_payload["packet"]["version"] == "1.2.3"
    assert lock_payload["artifacts"]["packet_manifest_hash"]


def test_build_command_fails_on_lock_input_mismatch(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    doc_path = project / "intro.md"
    doc_path.write_text("first", encoding="utf-8")

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
        vectors = [[1.0, 0.0, 0.0, 0.0] for _ in texts]
        return np.asarray(vectors, dtype=np.float32)

    monkeypatch.setattr(
        "cpm_builtin.embeddings.client.EmbeddingClient.embed_texts",
        fake_embed_texts,
    )

    first_result = cli_main(
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
    assert first_result == 0

    doc_path.write_text("second", encoding="utf-8")
    second_result = cli_main(
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
    assert second_result == 1

    third_result = cli_main(
        [
            "build",
            "run",
            "--source",
            "docs",
            "--name",
            "docs",
            "--packet-version",
            "1.2.3",
            "--update-lock",
        ],
        start_dir=tmp_path,
    )
    assert third_result == 0


def test_build_verify_detects_artifact_tampering(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("hello", encoding="utf-8")

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
        vectors = [[1.0, 0.0, 0.0, 0.0] for _ in texts]
        return np.asarray(vectors, dtype=np.float32)

    monkeypatch.setattr(
        "cpm_builtin.embeddings.client.EmbeddingClient.embed_texts",
        fake_embed_texts,
    )

    first_result = cli_main(
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
    assert first_result == 0

    packet_dir = tmp_path / "dist" / "docs" / "1.2.3"
    (packet_dir / "vectors.f16.bin").write_bytes(b"tampered")

    verify_result = cli_main(
        [
            "build",
            "verify",
            "--source",
            "docs",
            "--name",
            "docs",
            "--packet-version",
            "1.2.3",
        ],
        start_dir=tmp_path,
    )
    assert verify_result == 1

    update_result = cli_main(
        [
            "build",
            "lock",
            "--source",
            "docs",
            "--name",
            "docs",
            "--packet-version",
            "1.2.3",
            "--update-lock",
        ],
        start_dir=tmp_path,
    )
    assert update_result == 0

    lock_path = packet_dir / "packet.lock.json"
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["artifacts"]["embeddings_hash"]


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


def test_build_command_accepts_version_alias(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("Welcome\nThis is a sample project\nEnd", encoding="utf-8")

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
        vectors = [[1.0, 0.0, 0.0, 0.0] for _ in texts]
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
            "--version",
            "2.0.0",
        ],
        start_dir=tmp_path,
    )
    assert result == 0
    packet_dir = tmp_path / "dist" / "docs" / "2.0.0"
    manifest = load_manifest(packet_dir / "manifest.json")
    assert manifest.cpm["version"] == "2.0.0"


def test_build_command_uses_default_provider_from_embeddings_config(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("Welcome\nThis is a sample project\nEnd", encoding="utf-8")
    config_dir = tmp_path / ".cpm" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "embeddings.yml").write_text(
        (
            "default: local\n"
            "providers:\n"
            "  local:\n"
            "    type: http\n"
            "    url: http://embed.local:9999\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    def fake_health(self):
        return self.base_url == "http://embed.local:9999"

    monkeypatch.setattr("cpm_builtin.embeddings.client.EmbeddingClient.health", fake_health)

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
        vectors = [[1.0, 0.0, 0.0, 0.0] for _ in texts]
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
            "--version",
            "3.0.0",
        ],
        start_dir=tmp_path,
    )
    assert result == 0


def test_build_embed_generates_vectors_from_existing_chunks(tmp_path: Path, monkeypatch) -> None:
    packet_dir = tmp_path / "dist" / "docs" / "1.0.0"
    (packet_dir / "faiss").mkdir(parents=True, exist_ok=True)
    (packet_dir / "docs.jsonl").write_text(
        json.dumps({"id": "chunk-1", "text": "hello", "metadata": {"path": "intro.md", "ext": ".md"}}) + "\n",
        encoding="utf-8",
    )
    (packet_dir / "vectors.f16.bin").write_bytes(b"old")
    (packet_dir / "faiss" / "index.faiss").write_bytes(b"old")
    (packet_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "packet_id": "docs",
                "embedding": {
                    "provider": "sentence-transformers",
                    "model": "old-model",
                    "dim": 4,
                    "dtype": "float16",
                    "normalized": True,
                },
                "cpm": {"name": "docs", "version": "1.0.0", "description": "old"},
                "source": {"input_dir": str(tmp_path / "docs"), "file_ext_counts": {".md": 1}},
            }
        ),
        encoding="utf-8",
    )
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
        vectors = [[1.0, 0.0, 0.0, 0.0] for _ in texts]
        return np.asarray(vectors, dtype=np.float32)

    monkeypatch.setattr(
        "cpm_builtin.embeddings.client.EmbeddingClient.embed_texts",
        fake_embed_texts,
    )

    result = cli_main(
        [
            "build",
            "embed",
            "--source",
            str(packet_dir),
            "--model",
            "new-model",
        ],
        start_dir=tmp_path,
    )
    assert result == 0
    manifest = load_manifest(packet_dir / "manifest.json")
    assert manifest.embedding.model == "new-model"
    assert (packet_dir / "vectors.f16.bin").exists()
    assert (packet_dir / "faiss" / "index.faiss").exists()


def test_build_persists_docs_even_when_embedder_unreachable(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "intro.md").write_text("Hello\nWorld\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cpm_builtin.embeddings.client.EmbeddingClient.health", lambda self: False)

    result = cli_main(
        [
            "build",
            "run",
            "--source",
            "docs",
            "--name",
            "docs",
            "--version",
            "0.0.9",
        ],
        start_dir=tmp_path,
    )
    assert result == 1
    packet_dir = tmp_path / "dist" / "docs" / "0.0.9"
    assert (packet_dir / "docs.jsonl").exists()
    assert (packet_dir / "cpm.yml").exists()
    manifest = load_manifest(packet_dir / "manifest.json")
    assert manifest.cpm["name"] == "docs"
    assert manifest.cpm["version"] == "0.0.9"
    assert manifest.embedding.model == DefaultBuilderConfig().model_name
    assert manifest.embedding.dim == 0
    assert manifest.counts["docs"] >= 1
    assert manifest.counts["vectors"] == 0
    assert manifest.extras.get("build_status") == "embedding_failed"
