"""Tests for cache.py"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from ..cache import (
    CacheV3,
    FileCacheEntry,
    WindowCacheEntry,
    load_cache,
    save_cache,
    window_cache_key,
)
from ..schemas import Chunk, Window


def test_window_cache_key_consistent():
    """Test that window_cache_key is deterministic."""
    window = Window(
        id="test:win:1-100",
        path="test.py",
        text="def hello():\n    pass",
        start_line=1,
        end_line=2,
        language="python",
    )

    key1 = window_cache_key(window, "model1", "v1")
    key2 = window_cache_key(window, "model1", "v1")

    assert key1 == key2


def test_window_cache_key_changes_with_text():
    """Test that window_cache_key changes when text changes."""
    window1 = Window(
        id="test:win:1-100",
        path="test.py",
        text="def hello():\n    pass",
        start_line=1,
        end_line=2,
        language="python",
    )
    window2 = Window(
        id="test:win:1-100",
        path="test.py",
        text="def hello():\n    print('hi')",  # Different text
        start_line=1,
        end_line=2,
        language="python",
    )

    key1 = window_cache_key(window1, "model1", "v1")
    key2 = window_cache_key(window2, "model1", "v1")

    assert key1 != key2


def test_save_and_load_cache_v3():
    """Test round-trip save and load of v3 cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "cache.json"

        # Create cache
        chunk = Chunk(
            id="test:chunk:1",
            text="Hello world",
            summary="Test chunk",
            tags=("python",),
        )
        window_entry = WindowCacheEntry(window_hash="hash123", chunks=[chunk])
        file_entry = FileCacheEntry(
            source_hash="filehash",
            classification={"language": "python"},
            windows=[window_entry],
        )

        cache = CacheV3(files={"test.py": file_entry})

        # Save
        save_cache(cache_path, cache)

        # Load
        loaded = load_cache(cache_path)

        assert "test.py" in loaded.files
        assert loaded.files["test.py"].source_hash == "filehash"
        assert len(loaded.files["test.py"].windows) == 1
        assert len(loaded.files["test.py"].windows[0].chunks) == 1
        assert loaded.files["test.py"].windows[0].chunks[0].text == "Hello world"


def test_load_nonexistent_cache():
    """Test loading cache from nonexistent file returns empty cache."""
    cache = load_cache(Path("/nonexistent/cache.json"))
    assert isinstance(cache, CacheV3)
    assert len(cache.files) == 0


def test_migrate_v2_to_v3():
    """Test migration from v2 to v3 cache format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "cache.json"

        # Create v2 format cache
        v2_payload = {
            "version": 2,
            "files": {
                "test.py": {
                    "source_hash": "hash123",
                    "classification": {"language": "python"},
                    "segments": [],
                }
            },
            "segment_enrichment": {
                "seg1": {
                    "id": "chunk1",
                    "text": "Hello",
                    "summary": "Test",
                    "tags": ["python"],
                    "anchors": {"path": "test.py", "start_line": 1, "end_line": 2},
                }
            },
        }

        cache_path.write_text(json.dumps(v2_payload), encoding="utf-8")

        # Load (should migrate)
        cache = load_cache(cache_path)

        assert isinstance(cache, CacheV3)
        assert "test.py" in cache.files
        # Migrated segment_enrichment should become synthetic windows
        assert len(cache.files["test.py"].windows) > 0


def test_migrate_v1_to_v3():
    """Test migration from v1 (unversioned) to v3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "cache.json"

        # Create v1 format cache
        v1_payload = {
            "files": {
                "test.py": {
                    "source_hash": "hash123",
                    "chunks": ["chunk text 1", "chunk text 2"],
                }
            }
        }

        cache_path.write_text(json.dumps(v1_payload), encoding="utf-8")

        # Load (should migrate)
        cache = load_cache(cache_path)

        assert isinstance(cache, CacheV3)
        assert "test.py" in cache.files
        assert len(cache.files["test.py"].windows) > 0
