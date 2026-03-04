"""Tests for splitter.py"""

from __future__ import annotations

import pytest

from ..classifiers import FileClassification
from ..schemas import ChunkConstraints
from ..splitter import split_into_windows, _find_split_point


def test_find_split_point_finds_empty_line():
    """Test that _find_split_point finds nearby empty lines."""
    lines = ["line1", "line2", "", "line4", "line5"]
    result = _find_split_point(lines, target=3, search_radius=2)
    assert result == 2  # Found empty line at index 2


def test_find_split_point_no_empty_line():
    """Test that _find_split_point returns target if no empty line found."""
    lines = ["line1", "line2", "line3", "line4"]
    result = _find_split_point(lines, target=2, search_radius=1)
    assert result == 2  # No empty line, returns target


def test_split_small_file_single_window():
    """Test that small files create a single window."""
    content = "\n".join([f"line{i}" for i in range(50)])
    classification = FileClassification("code_generic", "python", "text/x-python")
    constraints = ChunkConstraints(window_lines=120)

    windows = split_into_windows("test.py", content, classification, constraints)

    assert len(windows) == 1
    assert windows[0].start_line == 1
    assert windows[0].end_line == 50
    assert windows[0].language == "python"


def test_split_large_file_multiple_windows():
    """Test that large files create multiple windows."""
    content = "\n".join([f"line{i}" for i in range(300)])
    classification = FileClassification("code_generic", "python", "text/x-python")
    constraints = ChunkConstraints(window_lines=100, overlap_lines=10)

    windows = split_into_windows("test.py", content, classification, constraints)

    assert len(windows) > 1
    # Check overlap exists
    assert windows[1].start_line < windows[0].end_line


def test_split_empty_file():
    """Test empty file handling."""
    content = ""
    classification = FileClassification("code_generic", "python", "text/x-python")
    constraints = ChunkConstraints(window_lines=120)

    windows = split_into_windows("test.py", content, classification, constraints)

    assert len(windows) == 0


def test_split_respects_paragraph_boundaries():
    """Test that splitter tries to align with empty lines."""
    lines = []
    for i in range(150):
        lines.append(f"line{i}")
        if i % 30 == 29:  # Add empty line every 30 lines
            lines.append("")

    content = "\n".join(lines)
    classification = FileClassification("code_generic", "python", "text/x-python")
    constraints = ChunkConstraints(window_lines=100, overlap_lines=5)

    windows = split_into_windows("test.py", content, classification, constraints)

    # Windows should align near empty lines
    assert len(windows) >= 2


def test_window_metadata():
    """Test that windows have correct metadata."""
    content = "\n".join([f"line{i}" for i in range(50)])
    classification = FileClassification("code_generic", "kotlin", "text/x-kotlin")
    constraints = ChunkConstraints(window_lines=120)

    windows = split_into_windows("Test.kt", content, classification, constraints)

    assert windows[0].language == "kotlin"
    assert windows[0].metadata["pipeline"] == "code_generic"
    assert windows[0].metadata["mime"] == "text/x-kotlin"
    assert windows[0].path == "Test.kt"
