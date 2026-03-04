"""Chunk cache v3: file-level + window-level caching with migration support."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from .schemas import Chunk, Segment, Window, stable_hash


CACHE_VERSION = 3


@dataclass
class WindowCacheEntry:
    """Cache entry for a single window's chunks."""
    window_hash: str
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class FileCacheEntry:
    """Cache entry for a file with window-level cache."""
    source_hash: str
    classification: dict[str, Any] = field(default_factory=dict)
    windows: list[WindowCacheEntry] = field(default_factory=list)


@dataclass
class CacheV3:
    """Cache v3: window-based chunking cache."""
    files: dict[str, FileCacheEntry] = field(default_factory=dict)


# Legacy v2 structures for migration
@dataclass
class FileCacheEntryV2:
    source_hash: str
    classification: dict[str, Any] = field(default_factory=dict)
    segments: list[Segment] = field(default_factory=list)


@dataclass
class CacheV2:
    files: dict[str, FileCacheEntryV2] = field(default_factory=dict)
    segment_enrichment: dict[str, Chunk] = field(default_factory=dict)


def window_cache_key(window: Window, model: str, prompt_version: str) -> str:
    """Generate cache key for a window + model + prompt combination."""
    payload = {
        "window_text_hash": stable_hash(window.text),
        "window_id": window.id,
        "model": model,
        "prompt_version": prompt_version,
    }
    return stable_hash(json.dumps(payload, sort_keys=True))


def load_cache(path: Path) -> CacheV3:
    """Load cache from disk, handling migrations from v1 and v2."""
    if not path.exists():
        return CacheV3()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return CacheV3()

    if not isinstance(payload, Mapping):
        return CacheV3()

    version = payload.get("version")

    if version == 3:
        return _load_v3(payload)
    elif version == 2:
        return _migrate_v2_to_v3(payload)
    else:
        # v1 or unversioned: migrate
        return _migrate_v1_to_v3(payload)


def _load_v3(payload: Mapping[str, Any]) -> CacheV3:
    """Load v3 cache format."""
    result = CacheV3()
    files_raw = payload.get("files")

    if isinstance(files_raw, Mapping):
        for rel, value in files_raw.items():
            if not isinstance(rel, str) or not isinstance(value, Mapping):
                continue

            source_hash = value.get("source_hash")
            if not isinstance(source_hash, str):
                continue

            cls = dict(value.get("classification") or {})
            windows_payload = value.get("windows") or []
            windows: list[WindowCacheEntry] = []

            if isinstance(windows_payload, list):
                for win_item in windows_payload:
                    if not isinstance(win_item, Mapping):
                        continue

                    window_hash = win_item.get("window_hash")
                    if not isinstance(window_hash, str):
                        continue

                    chunks_payload = win_item.get("chunks") or []
                    chunks: list[Chunk] = []

                    if isinstance(chunks_payload, list):
                        for chunk_item in chunks_payload:
                            if isinstance(chunk_item, Mapping):
                                try:
                                    chunks.append(Chunk.from_dict(chunk_item))
                                except Exception:
                                    continue

                    windows.append(
                        WindowCacheEntry(
                            window_hash=window_hash,
                            chunks=chunks,
                        )
                    )

            result.files[rel] = FileCacheEntry(
                source_hash=source_hash,
                classification=cls,
                windows=windows,
            )

    return result


def _migrate_v2_to_v3(payload: Mapping[str, Any]) -> CacheV3:
    """
    Migrate v2 cache to v3.

    Strategy: Convert segment_enrichment into synthetic window entries.
    These will be re-chunked on next file change.
    """
    result = CacheV3()

    # Load v2 files
    files_raw = payload.get("files")
    if isinstance(files_raw, Mapping):
        for rel, value in files_raw.items():
            if not isinstance(rel, str) or not isinstance(value, Mapping):
                continue

            source_hash = value.get("source_hash")
            if not isinstance(source_hash, str):
                continue

            cls = dict(value.get("classification") or {})

            # Create empty windows list for v3
            # Segments from v2 are discarded; enrichment cache converted below
            result.files[rel] = FileCacheEntry(
                source_hash=source_hash,
                classification=cls,
                windows=[],
            )

    # Convert segment_enrichment to a synthetic window
    # (Not ideal, but preserves cached data until next file edit)
    seg_enrichment = payload.get("segment_enrichment")
    if isinstance(seg_enrichment, Mapping):
        # Group chunks by file path
        chunks_by_path: dict[str, list[Chunk]] = {}

        for key, value in seg_enrichment.items():
            if not isinstance(value, Mapping):
                continue

            try:
                chunk = Chunk.from_dict(value)
                path = chunk.anchors.get("path", "")
                if path:
                    chunks_by_path.setdefault(path, []).append(chunk)
            except Exception:
                continue

        # Create synthetic windows for each path
        for path, chunks in chunks_by_path.items():
            if path not in result.files:
                # Orphaned chunks, create a minimal entry
                result.files[path] = FileCacheEntry(
                    source_hash="",
                    classification={},
                    windows=[],
                )

            # Create a synthetic window entry
            synthetic_window = WindowCacheEntry(
                window_hash="migrated_from_v2",
                chunks=chunks,
            )
            result.files[path].windows.append(synthetic_window)

    return result


def _migrate_v1_to_v3(payload: Mapping[str, Any]) -> CacheV3:
    """
    Migrate v1 (unversioned) cache to v3.

    v1 format: {"files": {"path": {"source_hash": "...", "chunks": [str, ...]}}}
    """
    result = CacheV3()
    files_raw = payload.get("files")

    if isinstance(files_raw, Mapping):
        for rel, entry in files_raw.items():
            if not isinstance(rel, str) or not isinstance(entry, Mapping):
                continue

            source_hash = entry.get("source_hash")
            if not isinstance(source_hash, str):
                continue

            # v1 had text chunks, convert to minimal Chunk objects
            chunks_raw = entry.get("chunks") or []
            chunks: list[Chunk] = []

            if isinstance(chunks_raw, list):
                for idx, item in enumerate(chunks_raw):
                    if isinstance(item, str):
                        text = item.strip()
                        if text:
                            chunks.append(
                                Chunk(
                                    id=f"{rel}:legacy:{idx}",
                                    text=text,
                                    title="",
                                    summary="",
                                    tags=(),
                                    anchors={"path": rel},
                                    window_id="v1_legacy",
                                )
                            )

            # Store as a synthetic window
            windows = [WindowCacheEntry(window_hash="migrated_from_v1", chunks=chunks)] if chunks else []

            result.files[rel] = FileCacheEntry(
                source_hash=source_hash,
                classification={"pipeline": "legacy"},
                windows=windows,
            )

    return result


def save_cache(path: Path, cache: CacheV3) -> None:
    """Save v3 cache to disk."""
    payload = {
        "version": CACHE_VERSION,
        "files": {
            rel: {
                "source_hash": entry.source_hash,
                "classification": dict(entry.classification),
                "windows": [
                    {
                        "window_hash": win.window_hash,
                        "chunks": [chunk.to_dict() for chunk in win.chunks],
                    }
                    for win in entry.windows
                ],
            }
            for rel, entry in sorted(cache.files.items())
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

