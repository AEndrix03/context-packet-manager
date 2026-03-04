"""Sliding window splitter for creating LLM-ready file windows."""

from __future__ import annotations

from .classifiers import FileClassification
from .schemas import ChunkConstraints, Window, stable_hash


def _find_split_point(lines: list[str], target: int, search_radius: int = 10) -> int:
    """
    Find an empty line near `target` within `search_radius`.
    If not found, return `target` exactly.

    This helps avoid splitting in the middle of logical blocks.
    """
    if target < 0 or target >= len(lines):
        return max(0, min(target, len(lines)))

    # Search both directions from target
    for delta in range(search_radius + 1):
        # Try before target
        candidate_before = target - delta
        if 0 <= candidate_before < len(lines) and not lines[candidate_before].strip():
            return candidate_before

        # Try after target
        candidate_after = target + delta
        if 0 <= candidate_after < len(lines) and not lines[candidate_after].strip():
            return candidate_after

    # No empty line found, use target
    return target


def split_into_windows(
    path: str,
    content: str,
    classification: FileClassification,
    constraints: ChunkConstraints,
) -> list[Window]:
    """
    Split file content into Windows for LLM processing.

    Strategy:
    - If file <= window_lines: single window (entire file)
    - If file > window_lines: sliding windows with overlap
    - Try to align window boundaries with empty lines (paragraph boundaries)

    Returns:
        List of Window objects ready for LLM chunking
    """
    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines == 0:
        return []

    window_lines = constraints.window_lines
    overlap_lines = constraints.overlap_lines

    # Small file: single window
    if total_lines <= window_lines:
        window_id = f"{path}:win:1-{total_lines}"
        return [
            Window(
                id=window_id,
                path=path,
                text=content,
                start_line=1,
                end_line=total_lines,
                language=classification.language,
                metadata={
                    "pipeline": classification.pipeline,
                    "mime": classification.mime,
                },
            )
        ]

    # Large file: sliding windows with overlap
    windows: list[Window] = []
    cursor = 0
    window_num = 1

    while cursor < total_lines:
        # Determine window end
        window_end = min(cursor + window_lines, total_lines)

        # Try to find a better split point (empty line) near the boundary
        if window_end < total_lines:
            window_end = _find_split_point(lines, window_end, search_radius=10)

        # Extract window text
        window_text = "\n".join(lines[cursor:window_end])

        # Create window ID
        start_line = cursor + 1  # 1-indexed
        end_line = window_end
        window_id = f"{path}:win:{start_line}-{end_line}:{stable_hash(window_text)[:8]}"

        windows.append(
            Window(
                id=window_id,
                path=path,
                text=window_text,
                start_line=start_line,
                end_line=end_line,
                language=classification.language,
                metadata={
                    "pipeline": classification.pipeline,
                    "mime": classification.mime,
                    "window_num": window_num,
                },
            )
        )

        # Move cursor forward, accounting for overlap
        # If this is the last window, break
        if window_end >= total_lines:
            break

        # Move cursor forward by (window_lines - overlap_lines)
        # This creates overlap between consecutive windows
        cursor = max(cursor + window_lines - overlap_lines, cursor + 1)
        window_num += 1

    return windows
