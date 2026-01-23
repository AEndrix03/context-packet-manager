import os
import json
from pathlib import Path
from typing import List, Dict, Any, Iterable

import numpy as np

from .schema import Chunk
from .chunkers.router import ChunkerRouter
from .chunkers.base import ChunkingConfig
from .embedder import JinaCodeEmbedder
from .faiss_db import FaissFlatIP

CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".java", ".kt", ".go", ".rs", ".cpp", ".c", ".h", ".cs"}
TEXT_EXTS = {".md", ".txt", ".rst"}

def iter_source_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in (CODE_EXTS | TEXT_EXTS):
            yield p

def read_text_file(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1")

def write_docs_jsonl(chunks: List[Chunk], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps({"id": c.id, "text": c.text, "metadata": c.metadata}, ensure_ascii=False) + "\n")

def build_component(
    input_dir: str,
    component_dir: str,
    model_name: str = "jinaai/jina-embeddings-v2-base-code",
    max_seq_length: int = 1024,
    lines_per_chunk: int = 80,
    overlap_lines: int = 10,
) -> None:
    in_root = Path(input_dir)
    out_root = Path(component_dir)

    print(f"[build] input_dir  = {in_root.resolve()}")
    print(f"[build] output_dir = {out_root.resolve()}")

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "faiss").mkdir(parents=True, exist_ok=True)

    # 1) scan + chunk
    chunks: List[Chunk] = []
    n_files = 0

    exts = sorted(CODE_EXTS | TEXT_EXTS)
    print(f"[scan] indexing extensions: {exts}")

    for file_path in iter_source_files(in_root):
        n_files += 1
        text = read_text_file(file_path)
        rel = str(file_path.relative_to(in_root)).replace("\\", "/")
        ext = file_path.suffix.lower()

        router = ChunkerRouter()
        cfg = ChunkingConfig(
            chunk_tokens=800,
            overlap_tokens=120,
            hard_cap_tokens=max_seq_length - 32,  # non sfori mai l'embedder
            mode="auto",
        )

        file_chunks = router.chunk(
            text=text,
            source_id=rel,
            ext=ext,
            config=cfg,
        )

        for c in file_chunks:
            c.metadata["path"] = rel
            c.metadata["ext"] = file_path.suffix.lower()
        chunks.extend(file_chunks)

        if n_files <= 5:
            print(f"[scan] + {rel} -> {len(file_chunks)} chunks")

    print(f"[scan] files_indexed={n_files}")
    print(f"[scan] chunks_total={len(chunks)}")

    if len(chunks) == 0:
        print("[error] No chunks found.")
        print("        - check --input_dir path")
        print("        - ensure there are files with supported extensions")
        return

    # 2) write docs
    docs_path = out_root / "docs.jsonl"
    write_docs_jsonl(chunks, docs_path)
    print(f"[write] docs.jsonl -> {docs_path} ({len(chunks)} lines)")

    # 3) embed
    embedder = JinaCodeEmbedder(model_name=model_name, max_seq_length=max_seq_length)
    dim = embedder.dim
    print(f"[embed] model={model_name}")
    print(f"[embed] dim={dim} max_seq_length={max_seq_length}")
    texts = [c.text for c in chunks]
    vecs = embedder.embed_texts(texts)  # float32, normalized
    print(f"[embed] vectors shape={vecs.shape} dtype={vecs.dtype}")

    # 4) faiss index + commit
    db = FaissFlatIP(dim=dim)
    db.add(vecs)
    print(f"[faiss] ntotal={db.index.ntotal}")

    index_path = out_root / "faiss" / "index.faiss"
    db.save(str(index_path))
    print(f"[write] faiss/index.faiss -> {index_path}")

    # 5) save vectors f16 (optional but matches your component format)
    vectors_path = out_root / "vectors.f16.bin"
    vecs.astype("float16").tofile(str(vectors_path))
    print(f"[write] vectors.f16.bin -> {vectors_path}")

    # 6) manifest
    manifest: Dict[str, Any] = {
        "schema_version": "1.0",
        "component_id": out_root.name,
        "embedding": {
            "provider": "sentence-transformers",
            "model": model_name,
            "dim": dim,
            "dtype": "float16",
            "normalized": True,
            "max_seq_length": max_seq_length,
        },
        "similarity": {
            "space": "cosine",
            "index_type": "faiss.IndexFlatIP",
            "notes": "cosine via inner product on L2-normalized vectors",
        },
        "files": {
            "docs": "docs.jsonl",
            "vectors": {"path": "vectors.f16.bin", "format": "f16_rowmajor"},
            "index": {"path": "faiss/index.faiss", "format": "faiss"},
            "calibration": None,
        },
        "counts": {"docs": len(chunks), "vectors": int(db.index.ntotal)},
    }
    manifest_path = out_root / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[write] manifest.json -> {manifest_path}")
    print("[done] build ok")