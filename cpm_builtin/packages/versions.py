"""Version parsing and ordering helpers reused by the package manager."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

__all__ = [
    "compare_versions",
    "normalize_latest",
    "split_version_parts",
    "version_key",
]

_STAGE_ORDER: dict[str, int] = {
    "dev": 0,
    "snapshot": 0,
    "nightly": 0,

    "a": 10,
    "alpha": 10,

    "b": 20,
    "beta": 20,

    "pre": 30,
    "preview": 30,

    "rc": 40,
    "candidate": 40,

    "stable": 90,
    "release": 90,
    "ga": 90,

    "final": 100,
}


def _safe_segment(seg: str) -> str:
    s = (seg or "").strip()
    if not s:
        return ""
    s = s.replace("\\", "/").replace("/", "-")
    s = re.sub(r"[^a-zA-Z0-9._\-+@]+", "-", s).strip("-")
    return s


def split_version_parts(version: str) -> List[str]:
    v = (version or "").strip()
    if not v:
        raise ValueError("empty version")
    raw = v.split(".")
    parts = [_safe_segment(p) for p in raw if p is not None and p != ""]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError(f"invalid version after sanitization: {version!r}")
    return parts


def normalize_latest(version: Optional[str]) -> Optional[str]:
    if version is None:
        return None
    v = version.strip()
    if not v:
        return None
    if v.lower() == "latest":
        return "latest"
    return v


def _split_segment_tokens(seg: str) -> Tuple[str, List[str]]:
    s = (seg or "").strip()
    if "-" not in s:
        return s, []
    parts = [p for p in s.split("-") if p != ""]
    if not parts:
        return s, []
    return parts[0], parts[1:]


def _tokenize_text_and_int(s: str) -> List[Any]:
    s = (s or "").strip()
    if not s:
        return []
    out: List[Any] = []
    i = 0
    while i < len(s):
        if s[i].isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            out.append((0, int(s[i:j])))
            i = j
        else:
            j = i
            while j < len(s) and not s[j].isdigit():
                j += 1
            out.append((1, s[i:j].lower()))
            i = j
    return out


def _qualifier_stage_and_num(tokens: List[str]) -> Tuple[int, int, Tuple[Any, ...]]:
    if not tokens:
        return (1000, 0, ())

    flat: List[Any] = []
    for token in tokens:
        flat.extend(_tokenize_text_and_int(token))

    stage_rank = None
    stage_num = 0
    extra: List[Any] = []

    for typ, val in flat:
        if typ == 1:
            if val in _STAGE_ORDER:
                stage_rank = _STAGE_ORDER[val]
                continue
            extra.append((typ, val))
        else:
            extra.append((typ, val))
        if stage_rank is not None:
            break

    if stage_rank is None:
        stage_rank = 50

    seen_stage = False
    for typ, val in flat:
        if typ == 1 and val in _STAGE_ORDER and not seen_stage:
            seen_stage = True
            continue
        if seen_stage and typ == 0:
            stage_num = val
            break

    return (stage_rank, stage_num, tuple(extra))


def _cmp_tokens(a: List[Any], b: List[Any]) -> int:
    la, lb = len(a), len(b)
    n = max(la, lb)
    for i in range(n):
        if i >= la:
            return -1
        if i >= lb:
            return 1
        ta, va = a[i]
        tb, vb = b[i]
        if ta != tb:
            return 1 if ta < tb else -1
        if va == vb:
            continue
        return 1 if va > vb else -1
    return 0


def compare_versions(a: str, b: str) -> int:
    aa = (a or "").strip()
    bb = (b or "").strip()
    if aa == bb:
        return 0

    seg_a = [s for s in aa.split(".") if s != ""]
    seg_b = [s for s in bb.split(".") if s != ""]

    n = max(len(seg_a), len(seg_b))
    for i in range(n):
        if i >= len(seg_a):
            return -1
        if i >= len(seg_b):
            return 1

        sa = seg_a[i]
        sb = seg_b[i]

        base_a, qual_a = _split_segment_tokens(sa)
        base_b, qual_b = _split_segment_tokens(sb)

        tok_a = _tokenize_text_and_int(base_a)
        tok_b = _tokenize_text_and_int(base_b)

        c = _cmp_tokens(tok_a, tok_b)
        if c != 0:
            return c

        stage_a = _qualifier_stage_and_num(qual_a)
        stage_b = _qualifier_stage_and_num(qual_b)
        if stage_a != stage_b:
            return 1 if stage_a > stage_b else -1

    return 0


def version_key(v: str) -> Tuple[Tuple[List[Any], int, int, Tuple[Any, ...]], ...]:
    segs = [s for s in (v or "").split(".") if s != ""]
    out: List[Tuple[List[Any], int, int, Tuple[Any, ...]]] = []
    for seg in segs:
        base, qual = _split_segment_tokens(seg)
        base_tokens = _tokenize_text_and_int(base)
        stage_rank, stage_num, extra = _qualifier_stage_and_num(qual)
        out.append((base_tokens, stage_rank, stage_num, extra))
    return tuple(out)
