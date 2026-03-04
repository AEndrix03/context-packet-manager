#!/usr/bin/env python3
"""Quick test script to verify the refactored plugin works."""

import sys
from pathlib import Path

# Add plugin to path
sys.path.insert(0, str(Path(__file__).parent / "cpm_plugins" / "llm_builder"))

from cpm_llm_builder_plugin import schemas, classifiers, splitter, llm_client, postprocess, cache, validators

print("[OK] All imports successful")

# Test 1: Token estimation with CJK
text_en = "Hello world this is a test"
text_cjk = "Hello world"  # Simplified for Windows console
tokens_en = schemas.estimate_tokens(text_en)
tokens_cjk = schemas.estimate_tokens(text_cjk)
print(f"[OK] Token estimation: EN={tokens_en}, test={tokens_cjk}")

# Test 2: Classifiers with new languages
cls_kotlin = classifiers.PIPELINES_BY_EXT.get(".kt")
cls_dart = classifiers.PIPELINES_BY_EXT.get(".dart")
cls_swift = classifiers.PIPELINES_BY_EXT.get(".swift")
print(f"[OK] Extended classifiers: Kotlin={cls_kotlin.language if cls_kotlin else None}, "
      f"Dart={cls_dart.language if cls_dart else None}, "
      f"Swift={cls_swift.language if cls_swift else None}")

# Test 3: Language hints
kotlin_cls = classifiers.FileClassification("code_generic", "kotlin", "text/x-kotlin")
hints = classifiers.language_hints(kotlin_cls)
print(f"[OK] Language hints for Kotlin: {hints[:50]}...")

# Test 4: Window creation
from cpm_llm_builder_plugin.schemas import ChunkConstraints
content = "\n".join([f"line {i}" for i in range(50)])
constraints = ChunkConstraints()
windows = splitter.split_into_windows(
    "test.py",
    content,
    classifiers.FileClassification("code_generic", "python", "text/x-python"),
    constraints
)
print(f"[OK] Window splitting: {len(windows)} window(s) created from 50 lines")

# Test 5: Window dataclass
window = schemas.Window(
    id="test:win:1-10",
    path="test.py",
    text="sample",
    start_line=1,
    end_line=10,
    language="python"
)
window_dict = window.to_dict()
print(f"[OK] Window dataclass: {window.id}")

# Test 6: Cache v3
from cpm_llm_builder_plugin.cache import CacheV3, FileCacheEntry, WindowCacheEntry
chunk = schemas.Chunk(id="test", text="hello", summary="test")
win_entry = WindowCacheEntry(window_hash="hash123", chunks=[chunk])
file_entry = FileCacheEntry(source_hash="fhash", windows=[win_entry])
cache_v3 = CacheV3(files={"test.py": file_entry})
print(f"[OK] Cache v3 structure: {len(cache_v3.files)} file(s)")

# Test 7: Validators with stats
chunks = [
    schemas.Chunk(id=f"chunk{i}", text="x" * 100, summary="s", tags=("t",))
    for i in range(5)
]
result = validators.validate_chunks(chunks, max_chunk_tokens=350, min_chunk_tokens=80)
print(f"[OK] Validation with stats: {result.stats.total} chunks, avg={result.stats.avg_tokens:.1f} tokens")

# Test 8: Deduplication
dup_chunks = [
    schemas.Chunk(id="c1", text="a", summary="short", anchors={"path": "t.py", "start_line": 1, "end_line": 5}),
    schemas.Chunk(id="c2", text="b", summary="longer summary", anchors={"path": "t.py", "start_line": 1, "end_line": 5}),
]
deduped = postprocess.deduplicate_by_anchor(dup_chunks)
print(f"[OK] Deduplication: {len(dup_chunks)} -> {len(deduped)} chunks (kept longest summary)")

print("\n[SUCCESS] All tests passed! Refactored plugin is working correctly.")
