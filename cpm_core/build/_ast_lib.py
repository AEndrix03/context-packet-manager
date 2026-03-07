"""
_ast_lib.py

Compile ``ast_chunk_core.c`` on first import and return a ready-to-use
ctypes.CDLL handle with typed function signatures.

Compilation is skipped when the .so / .dylib already exists and a stamp
file matching the source hash is present (i.e. the C source has not changed).
Set the ``CC`` environment variable to override the compiler (default: ``cc``).
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent.resolve()
_C_SRC = _HERE / "ast_chunk_core.c"

_SYSTEM = platform.system()
if _SYSTEM == "Darwin":
    _LIB_NAME = "ast_chunk_core.dylib"
elif _SYSTEM == "Windows":
    _LIB_NAME = "ast_chunk_core.dll"
else:
    _LIB_NAME = "ast_chunk_core.so"

_LIB_PATH = _HERE / _LIB_NAME


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _src_hash() -> str:
    """Short MD5 of the C source — used to invalidate the compiled artefact."""
    return hashlib.md5(_C_SRC.read_bytes()).hexdigest()[:16]


def _stamp_path() -> Path:
    return _HERE / f".ast_chunk_core.{_src_hash()}.stamp"


def _needs_compile() -> bool:
    if not _LIB_PATH.exists():
        return True
    # Recompile if the source has changed (stamp file gone or mismatched).
    return not _stamp_path().exists()


def _compile() -> None:
    cc = os.environ.get("CC", "cc")

    if _SYSTEM == "Darwin":
        flags = ["-O3", "-dynamiclib", "-fPIC"]
    elif _SYSTEM == "Windows":
        # MinGW / MSVC path; most CPM users will be on Linux/macOS.
        flags = ["-O3", "-shared"]
    else:
        flags = ["-O3", "-shared", "-fPIC"]

    cmd = [cc, *flags, "-o", str(_LIB_PATH), str(_C_SRC)]

    try:
        subprocess.check_call(cmd, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError(
            f"[ast_lib] C compiler not found (tried '{cc}'). "
            "Install gcc/clang or set the CC environment variable."
        ) from None
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(
            f"[ast_lib] Compilation of {_C_SRC.name} failed.\n{stderr}"
        ) from exc

    # Write stamp only after successful compilation.
    _stamp_path().touch()

    # Remove stale stamps from older versions.
    for stale in _HERE.glob(".ast_chunk_core.*.stamp"):
        if stale != _stamp_path():
            stale.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_lib: ctypes.CDLL | None = None


def load() -> ctypes.CDLL:
    """
    Return the compiled shared library as a ctypes handle.

    Thread-safety: ``load()`` is typically called once at module level inside
    ``ast_chunker.py``; repeat calls are O(1) (cached reference).
    """
    global _lib
    if _lib is not None:
        return _lib

    if _needs_compile():
        _compile()

    _lib = ctypes.CDLL(str(_LIB_PATH))

    # ---- nws_count ---------------------------------------------------------
    # int nws_count(const char *src, int start, int end)
    _lib.nws_count.restype = ctypes.c_int
    _lib.nws_count.argtypes = [
        ctypes.c_char_p,  # src
        ctypes.c_int,  # start
        ctypes.c_int,  # end
    ]

    # ---- cast_merge --------------------------------------------------------
    # int cast_merge(
    #     const int *nodes_start, const int *nodes_end, const int *nodes_nws,
    #     int n, int max_chunk_size,
    #     int *out_starts, int *out_ends)
    _int_p = ctypes.POINTER(ctypes.c_int)
    _lib.cast_merge.restype = ctypes.c_int
    _lib.cast_merge.argtypes = [
        _int_p, _int_p, _int_p,  # nodes_start, nodes_end, nodes_nws
        ctypes.c_int,  # n
        ctypes.c_int,  # max_chunk_size
        _int_p, _int_p,  # out_starts, out_ends
    ]

    return _lib
