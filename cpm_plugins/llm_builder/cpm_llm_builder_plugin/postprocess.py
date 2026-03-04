"""Post-processing rules for chunk size constraints."""

from __future__ import annotations

from typing import Sequence

from .schemas import Chunk, ChunkConstraints, estimate_tokens


def _resummary(text: str) -> str:
    """Fallback summary for automatically split chunks."""
    lines = text.strip().splitlines()
    if not lines:
        return ""
    first_line = lines[0][:120]
    return first_line + "…" if len(text) > 120 else first_line


def deduplicate_by_anchor(chunks: Sequence[Chunk]) -> list[Chunk]:
    """
    Deduplicate chunks from overlapping windows.

    Strategy: Keep chunk with longest summary for each unique anchor position.
    This assumes better summary = better LLM processing quality.
    """
    seen: dict[tuple[str, int, int], Chunk] = {}

    for chunk in chunks:
        path = chunk.anchors.get("path", "")
        start_line = chunk.anchors.get("start_line", 0)
        end_line = chunk.anchors.get("end_line", 0)

        key = (path, start_line, end_line)

        existing = seen.get(key)
        if existing is None:
            seen[key] = chunk
        else:
            # Keep chunk with longer summary (heuristic for quality)
            if len(chunk.summary) > len(existing.summary):
                seen[key] = chunk

    return list(seen.values())


def _split_chunk(chunk: Chunk, max_tokens: int) -> list[Chunk]:
    """
    Split oversized chunk into smaller parts.

    Important: Each split part gets a NEW summary based on its actual text,
    not inherited from the parent chunk (which described the whole block).
    """
    lines = chunk.text.splitlines()
    if not lines:
        return [chunk]

    result: list[Chunk] = []
    buffer: list[str] = []
    part = 0

    for line in lines:
        candidate = "\n".join(buffer + [line]).strip()
        if buffer and estimate_tokens(candidate) > max_tokens:
            text = "\n".join(buffer).strip()
            if text:
                # Generate new summary for this specific part
                part_summary = _resummary(text)
                result.append(
                    Chunk(
                        id=f"{chunk.id}:part:{part}",
                        text=text,
                        title=chunk.title if part == 0 else f"{chunk.title} (part {part})",
                        summary=part_summary,  # NEW: recalculated summary
                        tags=chunk.tags,
                        anchors=dict(chunk.anchors),
                        relations=dict(chunk.relations),
                        metadata=dict(chunk.metadata),
                        window_id=chunk.window_id,
                        chunk_tokens=estimate_tokens(text),
                    )
                )
                part += 1
            buffer = [line]
        else:
            buffer.append(line)

    final_text = "\n".join(buffer).strip()
    if final_text:
        final_summary = _resummary(final_text) if part > 0 else chunk.summary
        result.append(
            Chunk(
                id=f"{chunk.id}:part:{part}" if part > 0 else chunk.id,
                text=final_text,
                title=chunk.title if part == 0 else f"{chunk.title} (part {part})",
                summary=final_summary,
                tags=chunk.tags,
                anchors=dict(chunk.anchors),
                relations=dict(chunk.relations),
                metadata=dict(chunk.metadata),
                window_id=chunk.window_id,
                chunk_tokens=estimate_tokens(final_text),
            )
        )

    return result or [chunk]


def _merge_small_chunks(chunks: Sequence[Chunk], min_tokens: int) -> list[Chunk]:
    """
    Merge undersized chunks with adjacent chunks.

    Strategy: Keep merging forward until chunk reaches min_tokens.
    """
    if not chunks:
        return []

    merged: list[Chunk] = []
    buffer: Chunk | None = None

    for chunk in chunks:
        if buffer is None:
            buffer = chunk
            continue

        buffer_tokens = estimate_tokens(buffer.text)

        if buffer_tokens >= min_tokens:
            # Buffer is large enough, finalize it
            merged.append(buffer)
            buffer = chunk
            continue

        # Buffer is too small, merge with current chunk
        combined = f"{buffer.text}\n\n{chunk.text}".strip()
        buffer = Chunk(
            id=f"{buffer.id}+{chunk.id}",
            text=combined,
            title=buffer.title or chunk.title,
            summary=buffer.summary or chunk.summary,
            tags=tuple(sorted(set((*buffer.tags, *chunk.tags)))),
            anchors=dict(buffer.anchors),
            relations=dict(buffer.relations),
            metadata=dict(buffer.metadata),
            window_id=buffer.window_id or chunk.window_id,
            chunk_tokens=estimate_tokens(combined),
        )

    if buffer is not None:
        merged.append(buffer)

    return merged


def apply_chunk_constraints(chunks: Sequence[Chunk], constraints: ChunkConstraints) -> list[Chunk]:
    split_done: list[Chunk] = []
    for chunk in chunks:
        if estimate_tokens(chunk.text) > constraints.max_chunk_tokens:
            split_done.extend(_split_chunk(chunk, constraints.max_chunk_tokens))
        else:
            split_done.append(chunk)
    return _merge_small_chunks(split_done, constraints.min_chunk_tokens)

