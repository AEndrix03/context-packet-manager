"""Default builder implementation that produces CPM-compatible packets."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import tarfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Tuple

import numpy as np
from cpm_builtin.embeddings import EmbeddingClient

from cpm_core.api import CPMAbstractBuilder, cpmbuilder
from .ast_chunker import scan_directory
from cpm_core.packet.faiss_db import FaissFlatIP
from cpm_core.packet.io import (
    compute_checksums,
    load_manifest,
    read_docs_jsonl,
    write_docs_jsonl,
    write_manifest,
    write_vectors_f16,
)
from cpm_core.packet.models import DocChunk, EmbeddingSpec, PacketManifest

DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-code"
DEFAULT_EMBED_URL = "http://127.0.0.1:8876"
CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".cs",
}
TEXT_EXTS = {".md", ".txt", ".rst"}


class Embedder(Protocol):
    """Minimal interface required by the builder."""

    def health(self) -> bool:
        ...

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model_name: str,
        max_seq_length: int,
        normalize: bool,
        dtype: str,
        show_progress: bool,
    ) -> np.ndarray:
        ...


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embed_resilient(
    embedder: "Embedder",
    texts: list[str],
    chunk_ids: list[str],
    *,
    model_name: str,
    max_seq_length: int,
) -> tuple[list[int], Optional[np.ndarray], list[str]]:
    """Embed *texts* with per-chunk fallback on permanent errors.

    Returns ``(good_local_indices, vectors, skipped_ids)``:

    - ``good_local_indices`` : positions in *texts* that were embedded.
    - ``vectors``            : shape ``(len(good_local_indices), dim)``
                               or ``None`` if every chunk was skipped.
    - ``skipped_ids``        : chunk IDs that failed permanently.
    """
    _kw: Dict[str, Any] = dict(
        model_name=model_name,
        max_seq_length=max_seq_length,
        normalize=True,
        dtype="float32",
        show_progress=False,
    )
    try:
        vecs = embedder.embed_texts(texts, **_kw)
        return list(range(len(texts))), vecs, []
    except Exception as exc:
        print(f"[embed] batch failed ({exc}), falling back to per-chunk ...")

    good_indices: list[int] = []
    good_vecs: list[np.ndarray] = []
    skipped: list[str] = []
    total = len(texts)

    for local_idx, (text, cid) in enumerate(zip(texts, chunk_ids)):
        print(f"[embed] retry {local_idx + 1}/{total}: {cid}")
        try:
            vec = embedder.embed_texts([text], **_kw)
            good_indices.append(local_idx)
            good_vecs.append(vec[0])
        except Exception as chunk_exc:
            print(f"[embed] skip {cid}: {chunk_exc}")
            skipped.append(cid)

    if not good_vecs:
        return [], None, skipped
    return good_indices, np.vstack([v.reshape(1, -1) for v in good_vecs]), skipped


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _load_cpmignore(root: Path) -> list[str]:
    """Return non-blank, non-comment lines from ``<root>/.cpmignore``."""
    path = root / ".cpmignore"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _cpmignore_matches(rel_posix: str, patterns: list[str]) -> bool:
    """Return True if *rel_posix* should be skipped per the .cpmignore patterns.

    Supports the same syntax as .gitignore / .dockerignore:
    - ``#`` : comment
    - ``!pattern`` : negate a previous match
    - trailing ``/`` : directory-only match
    - ``*`` : any characters except ``/``
    - ``**`` : any characters including ``/`` (zero or more path segments)
    - ``?`` : any single character except ``/``
    - no ``/`` in pattern : matched against each path component (filename or dir name)
    - ``/`` in pattern : matched against the full relative path
    """
    parts = rel_posix.split("/")
    filename = parts[-1]
    ignored = False

    for raw in patterns:
        negate = raw.startswith("!")
        pat = raw[1:] if negate else raw
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        if not pat:
            continue

        hit = False
        if "**" in pat:
            # Convert ** to a multi-segment wildcard for fnmatch by trying the
            # pattern against every suffix of the path.
            flat = pat.replace("**", "*")
            hit = fnmatch.fnmatch(rel_posix, flat)
            if not hit:
                for i in range(len(parts)):
                    if fnmatch.fnmatch("/".join(parts[i:]), flat):
                        hit = True
                        break
        elif "/" not in pat:
            # No slash: match filename or any directory component.
            hit = fnmatch.fnmatch(filename, pat) or any(
                fnmatch.fnmatch(p, pat) for p in parts[:-1]
            )
        else:
            # Slash present: match against the full relative path.
            hit = fnmatch.fnmatch(rel_posix, pat)
            # For dir-only patterns also test path prefixes.
            if dir_only and not hit:
                for i in range(1, len(parts)):
                    if fnmatch.fnmatch("/".join(parts[:i]), pat):
                        hit = True
                        break

        if hit:
            ignored = not negate

    return ignored


def _build_bm25_index(chunks: list[DocChunk]) -> dict:
    """Pre-compute BM25 parameters for sparse/bm25.json.

    Format matches ``_bm25_hits()`` in query.py:
    ``{avgdl, doc_len, idf, tf}``
    """
    tokenized = [chunk.text.lower().split() for chunk in chunks]
    doc_count = max(len(tokenized), 1)
    avgdl = sum(len(t) for t in tokenized) / doc_count
    df: dict[str, int] = {}
    for tokens in tokenized:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    idf = {
        term: math.log(1 + (doc_count - freq + 0.5) / (freq + 0.5))
        for term, freq in df.items()
    }
    tf_list = []
    for tokens in tokenized:
        counts: dict[str, float] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0.0) + 1.0
        tf_list.append(counts)
    return {"avgdl": avgdl, "doc_len": [len(t) for t in tokenized], "idf": idf, "tf": tf_list}


def _scan_source(
    root: Path,
    *,
    max_chunk_size: int,
    # Parametri legacy mantenuti per compatibilità firma — ignorati
    lines_per_chunk: int = 0,
    overlap_lines: int = 0,
) -> tuple[list[DocChunk], Dict[str, int], int]:
    chunks: list[DocChunk] = []
    ext_counts: Dict[str, int] = {}
    rel_root = root.resolve()
    chunk_counter = 0
    files_indexed = 0
    files_ignored = 0

    ignore_patterns = _load_cpmignore(root)
    if ignore_patterns:
        print(f"[scan] .cpmignore: {len(ignore_patterns)} pattern(s) loaded")

    for file_path, ext, file_chunks in scan_directory(
        root, max_chunk_size=max_chunk_size
    ):
        rel = str(file_path.resolve().relative_to(rel_root)).replace("\\", "/")

        if ignore_patterns and _cpmignore_matches(rel, ignore_patterns):
            files_ignored += 1
            continue

        files_indexed += 1
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

        for chunk_text in file_chunks:
            chunks.append(
                DocChunk(
                    id=f"{rel}:{chunk_counter}",
                    text=chunk_text,
                    metadata={"path": rel, "ext": ext, "chunker": "ast"},
                )
            )
            chunk_counter += 1

    if files_ignored:
        print(f"[scan] {files_ignored} file(s) skipped via .cpmignore")

    return chunks, ext_counts, files_indexed


def _chunk_text(
    text: str, *, lines_per_chunk: int, overlap_lines: int
) -> Iterable[str]:
    if lines_per_chunk <= 0:
        lines_per_chunk = max(len(text.splitlines()), 1)
    overlap = max(min(overlap_lines, lines_per_chunk - 1), 0)
    lines = text.splitlines()
    if not lines:
        return []
    step = max(lines_per_chunk - overlap, 1)
    chunks: list[str] = []
    for start in range(0, len(lines), step):
        slice_end = min(start + lines_per_chunk, len(lines))
        chunk_lines = lines[start:slice_end]
        chunk_text = "\n".join(chunk_lines).strip()
        if chunk_text:
            chunks.append(chunk_text)
        if slice_end == len(lines):
            break
    return chunks


def _infer_tags(ext_counts: Dict[str, int]) -> list[str]:
    tags: list[str] = []

    def has(ext: str) -> bool:
        return ext_counts.get(ext, 0) > 0

    if has(".py"):
        tags.append("python")
    if has(".js"):
        tags.append("javascript")
    if has(".ts") or has(".tsx"):
        tags.append("typescript")
    if has(".java"):
        tags.append("java")
    if has(".kt"):
        tags.append("kotlin")
    if has(".go"):
        tags.append("go")
    if has(".rs"):
        tags.append("rust")
    if has(".cpp") or has(".c") or has(".h"):
        tags.append("cpp")
    if has(".cs"):
        tags.append("csharp")
    if has(".md") or has(".rst") or has(".txt"):
        tags.append("docs")
    tags.append("cpm")
    return sorted(set(tags))


def _write_cpm_yml(
    out_root: Path,
    *,
    name: str,
    version: str,
    description: str,
    tags: Sequence[str],
    entrypoints: Sequence[str],
    embedding_model: str,
    embedding_dim: int,
    embedding_normalized: bool,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def esc(value: str) -> str:
        if any(ch in value for ch in [":", "#", "\n", "\r", "\t"]):
            value = value.replace('"', '\\"')
            return f'"{value}"'
        return value

    cpm_path = out_root / "cpm.yml"
    with cpm_path.open("w", encoding="utf-8") as handle:
        handle.write("cpm_schema: 1\n")
        handle.write(f"name: {esc(name)}\n")
        handle.write(f"version: {esc(version)}\n")
        handle.write(f"description: {esc(description)}\n")
        handle.write(f"tags: {esc(','.join(tags))}\n")
        handle.write(f"entrypoints: {esc(','.join(entrypoints))}\n")
        handle.write(f"embedding_model: {esc(embedding_model)}\n")
        handle.write(f"embedding_dim: {int(embedding_dim)}\n")
        handle.write(
            f"embedding_normalized: {'true' if embedding_normalized else 'false'}\n"
        )
        handle.write(f"created_at: {esc(created_at)}\n")


def _archive_packet_dir(out_root: Path, archive_format: str) -> Path:
    if archive_format not in ("tar.gz", "zip"):
        raise ValueError(f"Unsupported archive format: {archive_format}")
    archive_path = Path(str(out_root) + (".tar.gz" if archive_format == "tar.gz" else ".zip"))
    if archive_path.exists():
        archive_path.unlink()
    if archive_format == "tar.gz":
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(out_root, arcname=out_root.name)
    else:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in out_root.rglob("*"):
                if item.is_file():
                    arcname = (Path(out_root.name) / item.relative_to(out_root)).as_posix()
                    archive.write(item, arcname)
    return archive_path


def _load_existing_cache(
    out_root: Path, *, model_name: str, max_seq_length: int
) -> Optional[Tuple[Dict[str, np.ndarray], int]]:
    manifest_path = out_root / "manifest.json"
    docs_path = out_root / "docs.jsonl"
    vectors_path = out_root / "vectors.f16.bin"
    if not (manifest_path.exists() and docs_path.exists() and vectors_path.exists()):
        return None
    try:
        manifest = load_manifest(manifest_path)
    except Exception:
        return None
    embedding = manifest.embedding
    if embedding.model != model_name or (
        embedding.max_seq_length is not None
        and embedding.max_seq_length != max_seq_length
    ):
        return None
    dim = embedding.dim
    hashes: list[str | None] = []
    try:
        with docs_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                h = entry.get("hash")
                if isinstance(h, str) and len(h) >= 32:
                    hashes.append(h)
                else:
                    hashes.append(None)
    except Exception:
        return None
    if not hashes:
        return None
    try:
        raw = np.fromfile(str(vectors_path), dtype=np.float16)
    except Exception:
        return None
    expected = len(hashes) * dim
    if raw.size != expected:
        return None
    mat_f32 = raw.reshape((len(hashes), dim)).astype(np.float32)
    cache: Dict[str, np.ndarray] = {}
    for idx, h in enumerate(hashes):
        if h is None or h in cache:
            continue
        cache[h] = mat_f32[idx].copy()
    return cache, dim


@dataclass(frozen=True)
class PacketMaterializationInput:
    source_path: Path
    out_root: Path
    packet_name: str
    packet_version: str
    description: str
    chunks: Sequence[DocChunk]
    ext_counts: Mapping[str, int]
    model_name: str
    max_seq_length: int
    archive: bool
    archive_format: str
    builder_name: str
    embedder: Embedder
    incremental_enabled: bool = True
    extra_files: Sequence[str] = ()
    extra_manifest: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DefaultBuilderConfig:
    model_name: str = DEFAULT_MODEL
    max_seq_length: int = 1024
    max_chunk_size: int = 300          # sostituisce lines_per_chunk
    lines_per_chunk: int = 80          # deprecated, ignorato
    overlap_lines: int = 10            # deprecated, ignorato
    version: str = "0.0.0"
    packet_name: str = "packet"
    description: str | None = None
    archive: bool = True
    archive_format: str = "tar.gz"
    embed_url: str = DEFAULT_EMBED_URL
    embeddings_mode: str = "http"
    timeout: float | None = None
    input_size: int | None = None


def materialize_packet(input_data: PacketMaterializationInput) -> PacketManifest | None:
    chunks = list(input_data.chunks)
    if not chunks:
        print("[error] No chunks found.")
        return None

    out_root = input_data.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "faiss").mkdir(parents=True, exist_ok=True)
    docs_path = out_root / "docs.jsonl"
    write_docs_jsonl(chunks, docs_path)
    print(f"[write] docs.jsonl -> {docs_path} ({len(chunks)} lines)")
    tags = _infer_tags(dict(input_data.ext_counts))

    def _write_partial_metadata(*, reason: str) -> PacketManifest:
        _write_cpm_yml(
            out_root,
            name=input_data.packet_name,
            version=input_data.packet_version,
            description=input_data.description,
            tags=tags,
            entrypoints=["query"],
            embedding_model=input_data.model_name,
            embedding_dim=0,
            embedding_normalized=True,
        )
        manifest = PacketManifest(
            schema_version="1.0",
            packet_id=input_data.packet_name,
            embedding=EmbeddingSpec(
                provider="sentence-transformers",
                model=input_data.model_name,
                dim=0,
                dtype="float16",
                normalized=True,
                max_seq_length=input_data.max_seq_length,
            ),
            similarity={
                "space": "cosine",
                "index_type": "faiss.IndexFlatIP",
                "notes": "vectors/index not materialized",
            },
            files={
                "docs": "docs.jsonl",
                "vectors": None,
                "index": None,
                "calibration": None,
            },
            counts={"docs": len(chunks), "vectors": 0},
            source={
                "input_dir": input_data.source_path.as_posix(),
                "file_ext_counts": dict(input_data.ext_counts),
            },
            cpm={
                "name": input_data.packet_name,
                "version": input_data.packet_version,
                "description": input_data.description,
                "tags": tags,
                "entrypoints": ["query"],
                "builder": input_data.builder_name,
            },
            incremental={
                "enabled": bool(cache_pack),
                "reused": 0,
                "embedded": 0,
                "removed": 0,
            },
            extras={"build_status": "embedding_failed", "build_error": reason},
        )
        if input_data.extra_manifest:
            manifest.extras.update(dict(input_data.extra_manifest))
        checksum_targets = ["cpm.yml", "docs.jsonl", *input_data.extra_files]
        manifest.checksums = compute_checksums(out_root, checksum_targets)
        manifest_path = out_root / "manifest.json"
        write_manifest(manifest, manifest_path)
        print(f"[write] manifest.json -> {manifest_path}")
        return manifest

    cache_pack = None
    if input_data.incremental_enabled:
        cache_pack = _load_existing_cache(
            out_root,
            model_name=input_data.model_name,
            max_seq_length=input_data.max_seq_length,
        )
    cache_vecs: Dict[str, np.ndarray] = {}
    cache_dim: Optional[int] = None
    if cache_pack:
        cache_vecs, cache_dim = cache_pack
        print(f"[cache] enabled: cached_vectors={len(cache_vecs)} dim={cache_dim}")
    else:
        print("[cache] disabled (no compatible previous build found)")

    new_hashes = [_chunk_hash(chunk.text) for chunk in chunks]
    new_set = set(new_hashes)
    prev_set = set(cache_vecs.keys())
    removed = len(prev_set - new_set) if cache_vecs else 0
    reused = sum(1 for h in new_hashes if h in cache_vecs)

    to_embed_idx: list[int] = []
    to_embed_texts: list[str] = []
    for idx, hsh in enumerate(new_hashes):
        if hsh not in cache_vecs:
            to_embed_idx.append(idx)
            to_embed_texts.append(chunks[idx].text)

    print(
        f"[cache] new_chunks={len(chunks)} reused={reused} to_embed={len(to_embed_idx)} removed={removed}"
    )

    if to_embed_idx:
        _chunks_per_file: dict[str, int] = {}
        for idx in to_embed_idx:
            fp = str(chunks[idx].metadata.get("path", chunks[idx].id))
            _chunks_per_file[fp] = _chunks_per_file.get(fp, 0) + 1
        print(f"[embed] {len(to_embed_idx)} chunks to embed from {len(_chunks_per_file)} file(s):")
        for _fp, _cnt in sorted(_chunks_per_file.items()):
            print(f"[embed]   {_fp}: {_cnt} chunk{'s' if _cnt != 1 else ''}")

    if not input_data.embedder.health():
        print("[error] embedding server is not reachable")
        _write_partial_metadata(reason="embedding server is not reachable")
        return None

    all_skipped_ids: list[str] = []
    vec_missing: Optional[np.ndarray] = None
    dim: Optional[int] = cache_dim

    # --- Main embed batch ---------------------------------------------------
    if to_embed_texts:
        to_embed_ids = [chunks[i].id for i in to_embed_idx]
        print(f"[embed] sending batch: {len(to_embed_texts)} chunks ...")
        _t0 = time.monotonic()
        good_local, vec_missing, skipped_ids = _embed_resilient(
            input_data.embedder,
            to_embed_texts,
            to_embed_ids,
            model_name=input_data.model_name,
            max_seq_length=input_data.max_seq_length,
        )
        _elapsed = time.monotonic() - _t0
        all_skipped_ids.extend(skipped_ids)
        to_embed_idx = [to_embed_idx[g] for g in good_local]
        to_embed_texts = [to_embed_texts[g] for g in good_local]
        if vec_missing is not None:
            dim = int(vec_missing.shape[1])
            print(f"[embed] done: {len(to_embed_idx)} chunks, dim={dim}, elapsed={_elapsed:.1f}s")
        elif not cache_vecs:
            reason = f"all {len(to_embed_ids)} chunks failed to embed"
            print(f"[error] {reason}")
            _write_partial_metadata(reason=reason)
            return None

    # --- Dim probe (all chunks cached, dim still unknown) -------------------
    elif dim is None and chunks:
        print("[embed] probing dim with first chunk ...")
        _t0 = time.monotonic()
        try:
            vec_missing = input_data.embedder.embed_texts(
                [chunks[0].text],
                model_name=input_data.model_name,
                max_seq_length=input_data.max_seq_length,
                normalize=True,
                dtype="float32",
                show_progress=False,
            )
            dim = int(vec_missing.shape[1])
            to_embed_idx = [0]
            print(f"[embed] probe done: dim={dim}, elapsed={time.monotonic() - _t0:.1f}s")
        except Exception as exc:
            print(f"[embed] probe failed: {exc}")
            _write_partial_metadata(reason=f"embedding request failed: {exc}")
            return None

    if dim is None:
        reason = "could not determine embedding dimension"
        print(f"[error] {reason}")
        _write_partial_metadata(reason=reason)
        return None

    # --- Dim-mismatch fallback: re-embed everything -------------------------
    if cache_dim is not None and cache_dim != dim:
        print(f"[cache] dim mismatch: cache_dim={cache_dim} new_dim={dim} -> cache disabled, re-embedding all {len(chunks)} chunks")
        cache_vecs = {}
        reused = 0
        all_ids = [c.id for c in chunks]
        all_texts = [c.text for c in chunks]
        print(f"[embed] sending batch: {len(all_texts)} chunks ...")
        _t0 = time.monotonic()
        good_local2, vec_missing, skipped_ids2 = _embed_resilient(
            input_data.embedder,
            all_texts,
            all_ids,
            model_name=input_data.model_name,
            max_seq_length=input_data.max_seq_length,
        )
        _elapsed = time.monotonic() - _t0
        all_skipped_ids.extend(skipped_ids2)
        to_embed_idx = good_local2
        to_embed_texts = [all_texts[g] for g in good_local2]
        if vec_missing is not None:
            dim = int(vec_missing.shape[1])
            print(f"[embed] done: {len(to_embed_idx)} chunks, dim={dim}, elapsed={_elapsed:.1f}s")

    # --- Filter out permanently skipped chunks ------------------------------
    if all_skipped_ids:
        skipped_set = set(all_skipped_ids)
        id_to_abs = {c.id: i for i, c in enumerate(chunks)}
        skipped_abs = {id_to_abs[sid] for sid in skipped_set if sid in id_to_abs}
        if skipped_abs:
            kept = [i for i in range(len(chunks)) if i not in skipped_abs]
            old_to_new = {old: new for new, old in enumerate(kept)}
            chunks = [chunks[i] for i in kept]
            new_hashes = [new_hashes[i] for i in kept]
            to_embed_idx = [old_to_new[i] for i in to_embed_idx if i in old_to_new]
            write_docs_jsonl(chunks, docs_path)
            print(
                f"[embed] {len(skipped_abs)} chunk(s) skipped; "
                f"docs.jsonl rewritten with {len(chunks)} chunk(s)"
            )

    if not chunks:
        reason = "all chunks failed to embed"
        print(f"[error] {reason}")
        _write_partial_metadata(reason=reason)
        return None

    # --- Build BM25 sparse index --------------------------------------------
    sparse_dir = out_root / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)
    bm25_path = sparse_dir / "bm25.json"
    bm25_data = _build_bm25_index(chunks)
    bm25_path.write_text(json.dumps(bm25_data, ensure_ascii=False), encoding="utf-8")
    print(f"[write] sparse/bm25.json -> {bm25_path} ({len(chunks)} docs)")

    # --- Assemble final vectors ---------------------------------------------
    final_vecs = np.empty((len(chunks), dim), dtype=np.float32)
    if cache_vecs:
        for idx, hsh in enumerate(new_hashes):
            vector = cache_vecs.get(hsh)
            if vector is not None:
                final_vecs[idx] = vector

    if to_embed_idx:
        assert vec_missing is not None
        for missing_idx, chunk_idx in enumerate(to_embed_idx):
            final_vecs[chunk_idx] = vec_missing[missing_idx]

    db = FaissFlatIP(dim=dim)
    db.add(final_vecs)
    db_path = out_root / "faiss" / "index.faiss"
    db.save(str(db_path))
    print(f"[write] faiss/index.faiss -> {db_path}")

    vectors_path = out_root / "vectors.f16.bin"
    write_vectors_f16(final_vecs, vectors_path)
    print(f"[write] vectors.f16.bin -> {vectors_path}")

    _write_cpm_yml(
        out_root,
        name=input_data.packet_name,
        version=input_data.packet_version,
        description=input_data.description,
        tags=tags,
        entrypoints=["query"],
        embedding_model=input_data.model_name,
        embedding_dim=dim,
        embedding_normalized=True,
    )

    manifest = PacketManifest(
        schema_version="1.0",
        packet_id=input_data.packet_name,
        embedding=EmbeddingSpec(
            provider="sentence-transformers",
            model=input_data.model_name,
            dim=dim,
            dtype="float16",
            normalized=True,
            max_seq_length=input_data.max_seq_length,
        ),
        similarity={
            "space": "cosine",
            "index_type": "faiss.IndexFlatIP",
            "notes": "cosine via inner product on normalized vectors",
        },
        files={
            "docs": "docs.jsonl",
            "vectors": {"path": "vectors.f16.bin", "format": "f16_rowmajor"},
            "index": {"path": "faiss/index.faiss", "format": "faiss"},
            "sparse": {"path": "sparse/bm25.json", "format": "bm25_json"},
            "calibration": None,
        },
        counts={"docs": len(chunks), "vectors": int(db.index.ntotal)},
        source={
            "input_dir": input_data.source_path.as_posix(),
            "file_ext_counts": dict(input_data.ext_counts),
        },
        cpm={
            "name": input_data.packet_name,
            "version": input_data.packet_version,
            "description": input_data.description,
            "tags": tags,
            "entrypoints": ["query"],
            "builder": input_data.builder_name,
        },
        incremental={
            "enabled": bool(cache_pack),
            "reused": reused,
            "embedded": len(to_embed_idx),
            "removed": removed,
        },
    )
    if input_data.extra_manifest:
        manifest.extras.update(dict(input_data.extra_manifest))
    if all_skipped_ids:
        manifest.extras["skipped_chunks"] = all_skipped_ids
        manifest.extras["skipped_chunks_count"] = len(all_skipped_ids)

    checksum_targets = ["cpm.yml", "docs.jsonl", "vectors.f16.bin", "faiss/index.faiss", "sparse/bm25.json", *input_data.extra_files]
    manifest.checksums = compute_checksums(out_root, checksum_targets)
    manifest_path = out_root / "manifest.json"
    write_manifest(manifest, manifest_path)
    print(f"[write] manifest.json -> {manifest_path}")

    if input_data.archive:
        archive_path = _archive_packet_dir(out_root, input_data.archive_format)
        print(f"[write] archive -> {archive_path}")

    if all_skipped_ids:
        print(f"[warn] {len(all_skipped_ids)} chunk(s) permanently skipped during embedding:")
        for sid in all_skipped_ids:
            print(f"[warn]   {sid}")

    print("[done] build ok")
    return manifest


def embed_packet_from_chunks(
    packet_dir: Path,
    *,
    model_name: str,
    max_seq_length: int,
    archive: bool,
    archive_format: str,
    embedder: Embedder,
    builder_name: str = "cpm:build-embed",
    packet_name_override: str | None = None,
    packet_version_override: str | None = None,
    description_override: str | None = None,
) -> PacketManifest | None:
    root = packet_dir.resolve()
    docs_path = root / "docs.jsonl"
    if not docs_path.exists():
        print(f"[error] docs.jsonl not found: {docs_path}")
        return None
    try:
        chunks = read_docs_jsonl(docs_path)
    except Exception as exc:
        print(f"[error] unable to read docs.jsonl: {exc}")
        return None
    if not chunks:
        print("[error] docs.jsonl contains no chunks")
        return None

    existing_manifest = None
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            existing_manifest = load_manifest(manifest_path)
        except Exception:
            existing_manifest = None

    packet_name = packet_name_override or (existing_manifest.cpm.get("name") if existing_manifest else None) or root.parent.name
    packet_version = packet_version_override or (existing_manifest.cpm.get("version") if existing_manifest else None) or root.name
    if not packet_name or not packet_version:
        print("[error] packet name/version are required")
        return None

    if description_override is not None and description_override.strip():
        description = description_override.strip()
    elif existing_manifest and str(existing_manifest.cpm.get("description") or "").strip():
        description = str(existing_manifest.cpm.get("description")).strip()
    elif existing_manifest and str(existing_manifest.source.get("input_dir") or "").strip():
        description = str(existing_manifest.source.get("input_dir")).strip()
    else:
        description = root.as_posix()

    source_input = (
        str(existing_manifest.source.get("input_dir") or "").strip()
        if existing_manifest is not None and isinstance(existing_manifest.source, dict)
        else ""
    )
    source_path = Path(source_input).expanduser() if source_input else root
    if not source_path.is_absolute():
        source_path = (root / source_path).resolve()
    if not source_path.exists():
        source_path = root

    ext_counts: Dict[str, int] = {}
    if existing_manifest is not None and isinstance(existing_manifest.source, dict):
        raw_ext = existing_manifest.source.get("file_ext_counts")
        if isinstance(raw_ext, dict):
            for key, value in raw_ext.items():
                try:
                    parsed = int(value)
                except Exception:
                    continue
                if parsed > 0:
                    ext_counts[str(key)] = parsed
    if not ext_counts:
        for chunk in chunks:
            ext = str(chunk.metadata.get("ext") or "").strip().lower()
            if not ext:
                continue
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    extra_files: list[str] = []
    extra_manifest = dict(existing_manifest.extras) if existing_manifest is not None else {}
    if existing_manifest is not None and isinstance(existing_manifest.files, dict):
        for value in existing_manifest.files.values():
            rel = None
            if isinstance(value, str):
                rel = value
            elif isinstance(value, dict) and isinstance(value.get("path"), str):
                rel = value.get("path")
            if rel is None:
                continue
            rel_norm = str(rel).replace("\\", "/").strip()
            if rel_norm in {"", "docs.jsonl", "vectors.f16.bin", "faiss/index.faiss"}:
                continue
            if (root / rel_norm).exists() and rel_norm not in extra_files:
                extra_files.append(rel_norm)

    print(f"[embed] packet_dir={root}")
    print(f"[embed] chunks_total={len(chunks)}")
    return materialize_packet(
        PacketMaterializationInput(
            source_path=source_path,
            out_root=root,
            packet_name=str(packet_name),
            packet_version=str(packet_version),
            description=description,
            chunks=chunks,
            ext_counts=ext_counts,
            model_name=model_name,
            max_seq_length=max_seq_length,
            archive=archive,
            archive_format=archive_format,
            builder_name=builder_name,
            embedder=embedder,
            incremental_enabled=False,
            extra_files=tuple(extra_files),
            extra_manifest=extra_manifest if extra_manifest else None,
        )
    )


@cpmbuilder(name="default-builder", group="cpm")
class DefaultBuilder(CPMAbstractBuilder):
    """Builder that indexes folders into CPM packets."""

    def __init__(
        self,
        config: DefaultBuilderConfig | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.config = config or DefaultBuilderConfig()
        self.embedder = embedder or EmbeddingClient(
            base_url=self.config.embed_url,
            mode=self.config.embeddings_mode,
            timeout_s=self.config.timeout,
            input_size=self.config.input_size,
        )

    def build(self, source: str, *, destination: str | None = None) -> PacketManifest | None:
        source_path = Path(source).resolve()
        if not source_path.exists():
            print(f"[error] source '{source_path}' does not exist")
            return None
        if destination is None:
            raise ValueError("destination path must be provided")

        out_root = Path(destination).resolve()
        print(f"[build] input_dir      = {source_path}")
        print(f"[build] output_dir     = {out_root}")
        print(f"[build] max_chunk_size = {self.config.max_chunk_size} non-ws chars")

        chunks, ext_counts, files_indexed = _scan_source(
            source_path,
            max_chunk_size=self.config.max_chunk_size,
        )
        print(f"[scan] files_indexed={files_indexed}")
        print(f"[scan] chunks_total={len(chunks)}")

        description = (self.config.description or source_path.as_posix()).strip() or source_path.as_posix()
        return materialize_packet(
            PacketMaterializationInput(
                source_path=source_path,
                out_root=out_root,
                packet_name=self.config.packet_name,
                packet_version=self.config.version,
                description=description,
                chunks=chunks,
                ext_counts=ext_counts,
                model_name=self.config.model_name,
                max_seq_length=self.config.max_seq_length,
                archive=self.config.archive,
                archive_format=self.config.archive_format,
                builder_name="cpm:default-builder",
                embedder=self.embedder,
                incremental_enabled=True,
            )
        )
