"""
ast_chunker.py

Language-agnostic, AST-aware chunker for CPM.

Algorithm (cAST — Zhang et al., 2025 / arXiv:2506.15655)
---------------------------------------------------------
1. Parse source bytes with tree-sitter → get root AST node.
2. Recursively collect "atomic nodes": the largest subtrees that fit
   within ``max_chunk_size`` non-whitespace characters, or forced leaves
   when a node cannot be split further.
3. Pass the atomic node list to the C ``cast_merge`` routine, which
   greedily merges adjacent nodes into chunks while respecting the budget.
4. Slice source bytes at the returned boundaries → decoded text chunks.

For unsupported / non-code file types a line-window fallback is used.

Tree-sitter parsing is O(n) in file size and fully in C; the Python code
only traverses the resulting node objects (also C structs under the hood).
The hot merge loop runs entirely in the compiled shared library.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Iterator

from ._ast_lib import load as _load_lib

# ---------------------------------------------------------------------------
# Language / extension tables
# ---------------------------------------------------------------------------

# Maps file extension → tree-sitter language name.
_EXT_TO_LANG: dict[str, str] = {
    # JVM
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    # Web / JS ecosystem
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    # Systems
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".rs": "rust",
    ".go": "go",
    ".swift": "swift",
    # Scripting
    ".py": "python",
    ".rb": "ruby",
    ".php": "php",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    # Query / data
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
}

# Extensions that exist as source but don't have a useful AST grammar;
# these fall back to the line-window chunker.
_TEXT_EXTS: frozenset[str] = frozenset({
    ".md", ".txt", ".rst",
    ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf",
    ".json", ".jsonc",
    ".xml", ".html", ".htm",
    ".properties", ".env",
    ".csv",
})

# Directories to skip entirely during directory scan.
SKIP_DIRS: frozenset[str] = frozenset({
    # VCS
    ".git", ".hg", ".svn",
    # JS / Python caches
    "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    # Build outputs
    "target", "build", "dist", "out", "bin", "obj",
    ".gradle", ".m2",
    # Virtual environments
    "venv", ".venv", "env", ".env",
    # IDE
    ".idea", ".vscode",
    # Vendored deps
    "vendor", "third_party",
})

# ---------------------------------------------------------------------------
# tree-sitter lazy parser cache
# ---------------------------------------------------------------------------

_parser_cache: dict[str, object] = {}  # lang_name → tree_sitter.Parser


def _get_parser(lang: str):
    """
    Return a cached tree-sitter Parser for *lang*, or None if unavailable.

    Tries ``tree_sitter_languages`` first (bundled grammars), then falls
    back to individually installed ``tree-sitter-<lang>`` packages.
    """
    if lang in _parser_cache:
        return _parser_cache[lang]

    # --- Strategy 1: tree_sitter_languages (covers 100+ languages) ---------
    try:
        from tree_sitter_languages import get_parser as _gp  # type: ignore
        parser = _gp(lang)
        _parser_cache[lang] = parser
        return parser
    except Exception:
        pass

    # --- Strategy 2: individual tree-sitter-<lang> packages -----------------
    try:
        import importlib
        mod_name = f"tree_sitter_{lang.replace('-', '_')}"
        mod = importlib.import_module(mod_name)
        from tree_sitter import Language, Parser  # type: ignore
        language = Language(mod.language())
        parser = Parser(language)
        _parser_cache[lang] = parser
        return parser
    except Exception:
        pass

    # Cache the negative result to avoid repeated import attempts.
    _parser_cache[lang] = None
    return None


# ---------------------------------------------------------------------------
# C bridge helpers
# ---------------------------------------------------------------------------

def _to_c_int_array(lst: list[int]) -> ctypes.Array:
    arr_type = ctypes.c_int * len(lst)
    return arr_type(*lst)


# ---------------------------------------------------------------------------
# cAST traversal  (Python side — runs on tree-sitter C objects)
# ---------------------------------------------------------------------------

def _collect_atomic(
        node,
        src: bytes,
        max_nws: int,
        lib: ctypes.CDLL,
        out: list[tuple[int, int, int]],
) -> None:
    """
    Recursively collect atomic nodes from *node*.

    A node is atomic when:
      • its non-ws size ≤ max_nws  (fits in a single chunk), OR
      • it has no children         (forced leaf — never discard content).

    When a node is too large and has children, we recurse into ALL children
    (named + anonymous) to maintain byte-perfect coverage of the source.
    """
    s, e = node.start_byte, node.end_byte
    nws: int = lib.nws_count(src, s, e)

    if nws == 0:
        return  # purely whitespace node — skip

    if nws <= max_nws or node.child_count == 0:
        out.append((s, e, nws))
        return

    # Node too large: recurse into every child (including punctuation nodes)
    # so that the resulting atomic list covers the full byte range.
    for child in node.children:
        _collect_atomic(child, src, max_nws, lib, out)


def _run_cast_merge(
        atomic: list[tuple[int, int, int]],
        max_chunk_size: int,
        lib: ctypes.CDLL,
) -> list[tuple[int, int]]:
    """
    Delegate the greedy merge step to the C ``cast_merge`` function.
    Returns a list of (start_byte, end_byte) chunk boundaries.
    """
    n = len(atomic)
    if n == 0:
        return []

    starts_arr = _to_c_int_array([a[0] for a in atomic])
    ends_arr = _to_c_int_array([a[1] for a in atomic])
    nws_arr = _to_c_int_array([a[2] for a in atomic])
    out_s = (ctypes.c_int * n)()
    out_e = (ctypes.c_int * n)()

    count: int = lib.cast_merge(
        starts_arr, ends_arr, nws_arr,
        n,
        max_chunk_size,
        out_s, out_e,
    )

    return [(out_s[i], out_e[i]) for i in range(count)]


# ---------------------------------------------------------------------------
# Line-window fallback  (for text/config files)
# ---------------------------------------------------------------------------

def _line_chunks(text: str, max_nws: int, overlap_lines: int = 5) -> list[str]:
    """
    Sliding-window chunker over lines.  Used for non-AST file types.

    Accumulates lines until the non-whitespace budget is exhausted, then
    flushes and keeps the last ``overlap_lines`` lines for context continuity.
    """
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[str] = []
    cur: list[str] = []
    cur_nws = 0

    def _nws(s: str) -> int:
        return sum(1 for c in s if c not in " \t\n\r")

    for line in lines:
        lnws = _nws(line)
        if cur_nws + lnws > max_nws and cur:
            text_chunk = "\n".join(cur).strip()
            if text_chunk:
                chunks.append(text_chunk)
            # Keep last N lines as overlap context
            cur = cur[-overlap_lines:]
            cur_nws = sum(_nws(l) for l in cur)
        cur.append(line)
        cur_nws += lnws

    if cur:
        tail = "\n".join(cur).strip()
        if tail:
            chunks.append(tail)

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_file(
        path: Path,
        *,
        max_chunk_size: int = 300,
) -> list[str]:
    """
    Chunk a single source file into semantically coherent text segments.

    Returns a list of non-empty strings, each representing one chunk.
    The concatenation of all chunks (ignoring stripped whitespace at
    boundaries) reconstructs the original file content.

    Parameters
    ----------
    path            : path to the source file
    max_chunk_size  : maximum non-whitespace character budget per chunk
                      (cAST paper default ≈ 300, maps to ~80–120 tokens)
    """
    lib = _load_lib()
    ext = path.suffix.lower()

    # --- Read source --------------------------------------------------------
    try:
        raw = path.read_bytes()
    except OSError:
        return []

    try:
        text = raw.decode("utf-8")
        src_bytes = raw
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        src_bytes = text.encode("utf-8")  # normalise to UTF-8 for tree-sitter

    if not text.strip():
        return []

    # --- Route to AST or line-based chunker ---------------------------------
    lang = _EXT_TO_LANG.get(ext)

    if lang is None:
        # Unknown or text-like extension → line-window fallback
        return _line_chunks(text, max_chunk_size)

    parser = _get_parser(lang)
    if parser is None:
        # Language grammar not installed → line-window fallback
        return _line_chunks(text, max_chunk_size)

    # --- cAST pipeline ------------------------------------------------------
    tree = parser.parse(src_bytes)
    atomic: list[tuple[int, int, int]] = []
    _collect_atomic(tree.root_node, src_bytes, max_chunk_size, lib, atomic)

    if not atomic:
        return []

    boundaries = _run_cast_merge(atomic, max_chunk_size, lib)

    chunks: list[str] = []
    for s, e in boundaries:
        chunk_text = src_bytes[s:e].decode("utf-8", errors="replace").strip()
        if chunk_text:
            chunks.append(chunk_text)

    return chunks


def scan_directory(
        root: Path,
        *,
        max_chunk_size: int = 300,
        extra_code_exts: frozenset[str] = frozenset(),
        extra_skip_dirs: frozenset[str] = frozenset(),
) -> Iterator[tuple[Path, str, list[str]]]:
    """
    Walk *root* recursively and yield ``(file_path, ext, chunks)`` for
    every indexed file.

    Files inside SKIP_DIRS (or ``extra_skip_dirs``) are silently ignored.
    Files whose extension is not in the supported set are skipped.
    Empty files or files that produce no chunks are skipped.

    Parameters
    ----------
    root             : directory to scan
    max_chunk_size   : non-whitespace char budget passed to ``chunk_file``
    extra_code_exts  : additional extensions to index (e.g. frozenset({".gradle"}))
    extra_skip_dirs  : additional directory names to skip
    """
    skip = SKIP_DIRS | extra_skip_dirs
    valid_exts = frozenset(_EXT_TO_LANG.keys()) | _TEXT_EXTS | extra_code_exts

    for file_path in sorted(root.rglob("*")):
        # Skip unwanted directories anywhere in the path
        if any(part in skip for part in file_path.parts):
            continue
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        if ext not in valid_exts:
            continue

        file_chunks = chunk_file(file_path, max_chunk_size=max_chunk_size)
        if file_chunks:
            yield file_path, ext, file_chunks
