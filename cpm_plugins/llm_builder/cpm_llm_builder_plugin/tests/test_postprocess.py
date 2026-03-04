"""Tests for postprocess.py"""

from __future__ import annotations

import pytest

from ..schemas import Chunk, ChunkConstraints
from ..postprocess import deduplicate_by_anchor, apply_chunk_constraints, _split_chunk


def test_deduplicate_by_anchor_removes_duplicates():
    """Test that chunks with same anchor are deduplicated."""
    chunks = [
        Chunk(
            id="chunk1",
            text="Hello world",
            summary="First summary",
            anchors={"path": "test.py", "start_line": 1, "end_line": 5},
        ),
        Chunk(
            id="chunk2",
            text="Hello world",
            summary="Better longer summary",
            anchors={"path": "test.py", "start_line": 1, "end_line": 5},
        ),
    ]

    result = deduplicate_by_anchor(chunks)

    assert len(result) == 1
    # Should keep the one with longer summary
    assert result[0].summary == "Better longer summary"


def test_deduplicate_keeps_different_anchors():
    """Test that chunks with different anchors are kept."""
    chunks = [
        Chunk(
            id="chunk1",
            text="Hello",
            anchors={"path": "test.py", "start_line": 1, "end_line": 5},
        ),
        Chunk(
            id="chunk2",
            text="World",
            anchors={"path": "test.py", "start_line": 6, "end_line": 10},
        ),
    ]

    result = deduplicate_by_anchor(chunks)

    assert len(result) == 2


def test_split_chunk_oversized():
    """Test splitting oversized chunks."""
    long_text = "\n".join([f"line {i}" for i in range(200)])
    chunk = Chunk(
        id="oversized",
        text=long_text,
        title="Big chunk",
        summary="Original summary",
        tags=("python", "function"),
    )

    result = _split_chunk(chunk, max_tokens=100)

    assert len(result) > 1
    # Each part should have its own summary (not inherited)
    for part in result:
        assert part.summary != ""
        assert "part" in part.id.lower() or part.id == chunk.id


def test_apply_chunk_constraints_splits_large():
    """Test that oversized chunks are split."""
    long_text = "\n".join([f"line {i}" for i in range(500)])
    chunk = Chunk(id="big", text=long_text)

    constraints = ChunkConstraints(max_chunk_tokens=200, min_chunk_tokens=50)
    result = apply_chunk_constraints([chunk], constraints)

    # Should be split into multiple chunks
    assert len(result) > 1


def test_apply_chunk_constraints_merges_small():
    """Test that small chunks are merged."""
    chunks = [
        Chunk(id="small1", text="a"),
        Chunk(id="small2", text="b"),
        Chunk(id="small3", text="c"),
    ]

    constraints = ChunkConstraints(max_chunk_tokens=1000, min_chunk_tokens=80)
    result = apply_chunk_constraints(chunks, constraints)

    # Should merge small chunks
    assert len(result) < len(chunks)


def test_apply_chunk_constraints_preserves_good_size():
    """Test that correctly sized chunks are unchanged."""
    good_text = "\n".join([f"line {i}" for i in range(50)])
    chunk = Chunk(id="good", text=good_text)

    constraints = ChunkConstraints(max_chunk_tokens=350, min_chunk_tokens=80)
    result = apply_chunk_constraints([chunk], constraints)

    assert len(result) == 1
    assert result[0].id == "good"
