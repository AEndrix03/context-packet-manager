"""Tests for validators.py"""

from __future__ import annotations

import pytest

from ..schemas import Chunk
from ..validators import validate_chunks, ChunkStats


def test_validate_drops_empty_chunks():
    """Test that chunks with empty text are dropped."""
    chunks = [
        Chunk(id="valid", text="Hello world"),
        Chunk(id="empty", text=""),
        Chunk(id="whitespace", text="   "),
    ]

    result = validate_chunks(chunks)

    assert len(result.chunks) == 1
    assert result.chunks[0].id == "valid"
    assert "empty text" in " ".join(result.warnings).lower()


def test_validate_drops_missing_id():
    """Test that chunks without id are dropped."""
    chunks = [
        Chunk(id="valid", text="Hello"),
        Chunk(id="", text="No ID"),
    ]

    result = validate_chunks(chunks)

    assert len(result.chunks) == 1
    assert "missing id" in " ".join(result.warnings).lower()


def test_validate_drops_duplicate_ids():
    """Test that duplicate IDs are detected."""
    chunks = [
        Chunk(id="dup", text="First"),
        Chunk(id="dup", text="Second"),
    ]

    result = validate_chunks(chunks)

    assert len(result.chunks) == 1
    assert "duplicate" in " ".join(result.warnings).lower()


def test_validate_warns_missing_path():
    """Test warning for missing anchor path."""
    chunks = [Chunk(id="test", text="Hello", anchors={})]

    result = validate_chunks(chunks)

    assert any("anchors.path" in w for w in result.warnings)


def test_validate_warns_missing_summary():
    """Test warning for missing summary."""
    chunks = [Chunk(id="test", text="Hello", summary="")]

    result = validate_chunks(chunks)

    assert any("summary" in w.lower() for w in result.warnings)


def test_validate_warns_missing_tags():
    """Test warning for missing tags."""
    chunks = [Chunk(id="test", text="Hello", tags=())]

    result = validate_chunks(chunks)

    assert any("tags" in w.lower() for w in result.warnings)


def test_validate_computes_stats():
    """Test that statistics are computed correctly."""
    chunks = [
        Chunk(id="chunk1", text="a" * 100, summary="sum", tags=("t1",)),
        Chunk(id="chunk2", text="b" * 200, summary="sum", tags=("t2",)),
        Chunk(id="chunk3", text="c" * 150, summary="sum", tags=("t3",)),
    ]

    result = validate_chunks(chunks, max_chunk_tokens=200, min_chunk_tokens=80)

    assert result.stats.total == 3
    assert result.stats.avg_tokens > 0
    assert result.stats.min_tokens > 0
    assert result.stats.max_tokens > result.stats.min_tokens


def test_validate_warns_oversized():
    """Test warning for oversized chunks."""
    long_text = "x" * 2000
    chunks = [Chunk(id="huge", text=long_text, summary="s", tags=("t",))]

    result = validate_chunks(chunks, max_chunk_tokens=350)

    assert any("exceed" in w.lower() for w in result.warnings)
    assert result.stats.oversized > 0


def test_validate_warns_high_avg():
    """Test warning when avg tokens is too high."""
    # Create chunks that average > 400 tokens
    chunks = [
        Chunk(id=f"chunk{i}", text="x" * 2000, summary="s", tags=("t",))
        for i in range(5)
    ]

    result = validate_chunks(chunks, max_chunk_tokens=1000)

    # Should warn about high average
    warnings_text = " ".join(result.warnings).lower()
    assert "avg" in warnings_text or "average" in warnings_text
