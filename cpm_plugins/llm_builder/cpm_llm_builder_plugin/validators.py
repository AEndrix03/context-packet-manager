"""Validation and quality gates for final chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .schemas import Chunk, estimate_tokens


@dataclass(frozen=True)
class ChunkStats:
    """Statistics about chunk sizes and quality."""
    total: int
    avg_tokens: float
    min_tokens: int
    max_tokens: int
    oversized: int  # chunks > max_chunk_tokens
    undersized: int  # chunks < min_chunk_tokens
    missing_summary: int
    missing_tags: int


@dataclass(frozen=True)
class ValidationResult:
    chunks: tuple[Chunk, ...]
    warnings: tuple[str, ...]
    stats: ChunkStats


def validate_chunks(
    chunks: Sequence[Chunk],
    *,
    max_chunk_tokens: int = 350,
    min_chunk_tokens: int = 80,
) -> ValidationResult:
    """
    Validate chunks and compute statistics.

    Args:
        chunks: Sequence of chunks to validate
        max_chunk_tokens: Threshold for oversized warning
        min_chunk_tokens: Threshold for undersized warning

    Returns:
        ValidationResult with valid chunks, warnings, and statistics
    """
    warnings: list[str] = []
    seen: set[str] = set()
    valid: list[Chunk] = []

    # Validation pass
    for chunk in chunks:
        if not chunk.text.strip():
            warnings.append(f"chunk {chunk.id!r} dropped: empty text")
            continue
        if not chunk.id:
            warnings.append("chunk dropped: missing id")
            continue
        if chunk.id in seen:
            warnings.append(f"chunk {chunk.id!r} dropped: duplicate id")
            continue
        seen.add(chunk.id)

        anchors = dict(chunk.anchors)
        if "path" not in anchors:
            warnings.append(f"chunk {chunk.id!r} has no anchors.path")
        if not chunk.summary:
            warnings.append(f"chunk {chunk.id!r} has empty summary")
        if not chunk.tags:
            warnings.append(f"chunk {chunk.id!r} has empty tags")

        valid.append(chunk)

    # Statistics pass
    if valid:
        token_counts = [estimate_tokens(chunk.text) for chunk in valid]
        avg_tokens = sum(token_counts) / len(token_counts)
        min_token_count = min(token_counts)
        max_token_count = max(token_counts)
        oversized = sum(1 for t in token_counts if t > max_chunk_tokens)
        undersized = sum(1 for t in token_counts if t < min_chunk_tokens)
        missing_summary = sum(1 for chunk in valid if not chunk.summary.strip())
        missing_tags = sum(1 for chunk in valid if not chunk.tags)

        stats = ChunkStats(
            total=len(valid),
            avg_tokens=avg_tokens,
            min_tokens=min_token_count,
            max_tokens=max_token_count,
            oversized=oversized,
            undersized=undersized,
            missing_summary=missing_summary,
            missing_tags=missing_tags,
        )

        # Add warning if average chunk size is too large
        if avg_tokens > 400:
            warnings.append(
                f"WARNING: avg chunk size {avg_tokens:.0f} tokens — "
                f"consider reducing window_lines or max_chunk_tokens"
            )

        # Add warning if many chunks are oversized
        if oversized > 0:
            warnings.append(f"WARNING: {oversized} chunk(s) exceed {max_chunk_tokens} tokens")

        # Add warning if many chunks are undersized
        if undersized > len(valid) * 0.3:  # More than 30% undersized
            warnings.append(
                f"WARNING: {undersized} chunk(s) below {min_chunk_tokens} tokens "
                f"({undersized * 100 // len(valid)}% of total)"
            )

    else:
        # No valid chunks
        stats = ChunkStats(
            total=0,
            avg_tokens=0.0,
            min_tokens=0,
            max_tokens=0,
            oversized=0,
            undersized=0,
            missing_summary=0,
            missing_tags=0,
        )

    return ValidationResult(chunks=tuple(valid), warnings=tuple(warnings), stats=stats)

