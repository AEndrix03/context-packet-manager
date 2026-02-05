from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from .models import DocChunk, PacketManifest


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_docs_jsonl(chunks: Iterable[DocChunk], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            entry: dict[str, object | str] = {
                "id": chunk.id,
                "text": chunk.text,
                "hash": _chunk_hash(chunk.text),
                "metadata": chunk.metadata,
            }
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")


def read_docs_jsonl(path: Path) -> list[DocChunk]:
    chunks: list[DocChunk] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            metadata = dict(entry.get("metadata") or {})
            chunk = DocChunk(id=str(entry["id"]), text=str(entry["text"]), metadata=metadata)
            chunks.append(chunk)
    return chunks


def write_vectors_f16(vectors: np.ndarray, path: Path) -> None:
    np.asarray(vectors, dtype=np.float16).tofile(str(path))


def read_vectors_f16(path: Path, dim: int) -> np.ndarray:
    if dim <= 0:
        raise ValueError("dim must be positive")
    raw = np.fromfile(str(path), dtype=np.float16)
    if raw.size % dim != 0:
        raise ValueError(f"vectors file length {raw.size} is not divisible by dim={dim}")
    reshaped = raw.reshape(-1, dim)
    return reshaped.astype(np.float32)


def compute_checksums(root: Path, relative_paths: Iterable[str]) -> dict[str, dict[str, str]]:
    checksums: dict[str, dict[str, str]] = {}
    for rel in relative_paths:
        target = root / rel
        if not target.exists():
            continue
        rel_str = rel.replace("\\", "/")
        checksums[rel_str] = {"algo": "sha256", "value": _sha256_file(target)}
    return checksums


def load_manifest(path: Path) -> PacketManifest:
    return PacketManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_manifest(manifest: PacketManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
