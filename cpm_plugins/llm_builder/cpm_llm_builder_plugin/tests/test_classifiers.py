"""Tests for classifiers.py"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..classifiers import FileClassification, PIPELINES_BY_EXT, classify_file, language_hints


def test_pipelines_by_ext_contains_common_languages():
    """Test that all major languages are registered."""
    expected = [
        ".py", ".java", ".js", ".ts", ".tsx", ".go", ".rs", ".c", ".cpp", ".cs",
        ".kt", ".scala", ".dart", ".swift", ".php", ".rb", ".lua", ".sh",
        ".vue", ".sql", ".proto", ".tf", ".md", ".json", ".yaml", ".toml", ".xml"
    ]
    for ext in expected:
        assert ext in PIPELINES_BY_EXT, f"Extension {ext} should be in PIPELINES_BY_EXT"


def test_classify_python_file():
    """Test Python file classification."""
    path = Path("test.py")
    content = "def hello():\n    print('world')"
    result = classify_file(path, content)
    assert result.language == "python"
    assert result.pipeline == "code_generic"
    assert result.is_supported_text


def test_classify_kotlin_file():
    """Test Kotlin file classification."""
    path = Path("Test.kt")
    content = "fun main() { println(\"hello\") }"
    result = classify_file(path, content)
    assert result.language == "kotlin"
    assert result.is_supported_text


def test_classify_shebang_python():
    """Test shebang detection for Python."""
    path = Path("script")
    content = "#!/usr/bin/env python3\nprint('hello')"
    result = classify_file(path, content)
    assert result.language == "python"


def test_classify_shebang_bash():
    """Test shebang detection for bash."""
    path = Path("script.sh")
    content = "#!/bin/bash\necho hello"
    result = classify_file(path, content)
    assert result.language == "shell"


def test_classify_dockerfile():
    """Test Dockerfile classification."""
    path = Path("Dockerfile")
    content = "FROM ubuntu:20.04\nRUN apt-get update"
    result = classify_file(path, content)
    assert result.language == "dockerfile"


def test_classify_binary_file():
    """Test binary file detection."""
    path = Path("binary.bin")
    content = "hello\x00world"
    result = classify_file(path, content)
    assert not result.is_supported_text
    assert result.language == "binary"


def test_language_hints_kotlin():
    """Test language hints for Kotlin."""
    cls = FileClassification("code_generic", "kotlin", "text/x-kotlin")
    hints = language_hints(cls)
    assert "fun" in hints
    assert "class" in hints


def test_language_hints_dart():
    """Test language hints for Dart."""
    cls = FileClassification("code_generic", "dart", "text/x-dart")
    hints = language_hints(cls)
    assert "Widget" in hints or "class" in hints


def test_language_hints_unknown():
    """Test language hints for unknown language returns empty."""
    cls = FileClassification("code_generic", "unknown_lang", "text/plain")
    hints = language_hints(cls)
    assert hints == ""
