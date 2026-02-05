import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from cpm_core.packet import (
    DocChunk,
    EmbeddingSpec,
    PacketManifest,
    FaissFlatIP,
    load_faiss_index,
    load_manifest,
    compute_checksums,
    read_docs_jsonl,
    read_vectors_f16,
    write_docs_jsonl,
    write_manifest,
    write_vectors_f16,
)


def _make_sample_chunks() -> list[DocChunk]:
    return [
        DocChunk(id="doc-1", text="hello world", metadata={"path": "foo.txt"}),
        DocChunk(id="doc-2", text="goodbye", metadata={"path": "bar.md"}),
    ]


def _make_manifest() -> PacketManifest:
    embedding = EmbeddingSpec(
        provider="sentence-transformers",
        model="jinaai/jina-embeddings-v2-base-code",
        dim=4,
        dtype="float16",
        normalized=True,
        max_seq_length=1024,
    )
    return PacketManifest(
        schema_version="1.0",
        packet_id="test-packet",
        embedding=embedding,
        similarity={"space": "cosine"},
        files={
            "docs": "docs.jsonl",
            "vectors": {"path": "vectors.f16.bin", "format": "f16_rowmajor"},
            "index": {"path": "faiss/index.faiss", "format": "faiss"},
            "calibration": None,
        },
        counts={"docs": 2, "vectors": 2},
        source={"input_dir": "/src", "file_ext_counts": {".py": 1}},
        cpm={"name": "test-packet", "version": "0.0.1", "tags": ["cpm"], "entrypoints": ["query"]},
        incremental={"enabled": False, "reused": 0, "embedded": 2, "removed": 0},
        checksums={"docs.jsonl": {"algo": "sha256", "value": "000"}},
        extras={"legacy_flag": True},
    )


def test_docs_roundtrip(tmp_path: Path) -> None:
    docs_path = tmp_path / "docs.jsonl"
    chunks = _make_sample_chunks()
    write_docs_jsonl(chunks, docs_path)
    assert read_docs_jsonl(docs_path) == chunks


def test_vectors_roundtrip(tmp_path: Path) -> None:
    vectors = np.arange(12, dtype=np.float32).reshape(3, 4)
    vec_path = tmp_path / "vectors.f16.bin"
    write_vectors_f16(vectors, vec_path)
    loaded = read_vectors_f16(vec_path, dim=4)
    np.testing.assert_allclose(loaded, vectors, rtol=1e-3, atol=1e-3)


def test_manifest_roundtrip(tmp_path: Path) -> None:
    manifest = _make_manifest()
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest, manifest_path)
    reloaded = load_manifest(manifest_path)
    assert reloaded == manifest


def test_compute_checksums(tmp_path: Path) -> None:
    docs_path = tmp_path / "docs.jsonl"
    docs_path.write_text("hi", encoding="utf-8")
    paths = ["docs.jsonl", "missing.file"]
    hashes = compute_checksums(tmp_path, paths)
    assert "docs.jsonl" in hashes
    assert "missing.file" not in hashes
    expected = hashlib.sha256(b"hi").hexdigest()
    assert hashes["docs.jsonl"]["value"] == expected


def test_load_legacy_manifest(tmp_path: Path) -> None:
    legacy_data = {
        "schema_version": "legacy",
        "packet_id": "legacy-packet",
        "embedding": {
            "provider": "sentence-transformers",
            "model": "legacy",
            "dim": 8,
            "dtype": "float16",
            "normalized": True,
            "max_seq_length": 1024,
        },
        "counts": {"docs": 1, "vectors": 1},
        "files": {"docs": "docs.jsonl"},
        "similarity": {"space": "cosine"},
        "source": {"input_dir": "/legacy"},
        "cpm": {},
        "incremental": {},
        "checksums": {"docs.jsonl": {"algo": "sha256", "value": ""}},
        "extra_prop": {"flag": True},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(legacy_data), encoding="utf-8")
    manifest = load_manifest(path)
    assert manifest.packet_id == "legacy-packet"
    assert manifest.embedding.model == "legacy"
    assert manifest.extras["extra_prop"]["flag"]


def test_faiss_index_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("faiss")
    vectors = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float32)
    db = FaissFlatIP(dim=4)
    db.add(vectors)
    index_path = tmp_path / "faiss" / "index.faiss"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    db.save(index_path)
    loaded = load_faiss_index(index_path)
    scores, ids = loaded.search(vectors[:1], 1)
    assert ids[0][0] == 0
