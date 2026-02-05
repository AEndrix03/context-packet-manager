from pathlib import Path

import pytest

from cpm_builtin.chunking import ChunkerRouter, ChunkingConfig

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "chunking"
FIXTURES = {
    "sample.py": ".py",
    "sample.java": ".java",
    "sample.md": ".md",
}
EXPECTED_CHUNKERS = {
    ".py": "python_ast",
    ".java": "java",
    ".md": "markdown",
}


@pytest.mark.parametrize("filename, ext", FIXTURES.items())
def test_chunk_router_is_deterministic(filename: str, ext: str) -> None:
    path = FIXTURE_DIR / filename
    text = path.read_text(encoding="utf-8")

    router = ChunkerRouter()
    first = router.chunk(text, source_id=path.name, ext=ext, config=ChunkingConfig())
    second = router.chunk(text, source_id=path.name, ext=ext, config=ChunkingConfig())

    assert first, "Expected at least one chunk"
    assert len(first) == len(second)

    expected_chunker = EXPECTED_CHUNKERS[ext]
    for chunk_a, chunk_b in zip(first, second):
        assert chunk_a.id == chunk_b.id
        assert chunk_a.text == chunk_b.text
        assert chunk_a.metadata == chunk_b.metadata
        chunker_name = chunk_a.metadata.get("chunker", "")
        assert chunker_name.startswith(expected_chunker)
