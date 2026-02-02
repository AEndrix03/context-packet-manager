from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# MCP (official python SDK)
# pip install mcp
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="context-packet-manager")


# ----------------------------
# Helpers (lookup)
# ----------------------------

def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _read_simple_yml(path: Path) -> Dict[str, str]:
    """
    Parser minimale per:
      key: value
    NO liste, NO nesting.
    """
    out: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out
    except UnicodeDecodeError:
        lines = path.read_text(encoding="latin-1").splitlines()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _split_csv(v: Optional[str]) -> List[str]:
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


def _extract_packet_info(packet_root: Path) -> Dict[str, Any]:
    manifest = _read_json(packet_root / "manifest.json") or {}
    yml = _read_simple_yml(packet_root / "cpm.yml")

    name = yml.get("name") or manifest.get("packet_id") or packet_root.name
    version = yml.get("version") or manifest.get("cpm", {}).get("version") or "unknown"
    description = yml.get("description") or ""
    tags = _split_csv(yml.get("tags"))
    entrypoints = _split_csv(yml.get("entrypoints"))

    embedding = manifest.get("embedding") or {}
    emb_model = yml.get("embedding_model") or embedding.get("model")
    emb_dim = yml.get("embedding_dim") or embedding.get("dim")
    emb_norm = yml.get("embedding_normalized")
    if emb_norm is None:
        emb_norm = embedding.get("normalized")

    counts = manifest.get("counts") or {}

    return {
        "name": name,
        "version": version,
        "description": description,
        "tags": tags,
        "entrypoints": entrypoints,
        "dir_name": packet_root.name,
        "path": str(packet_root).replace("\\", "/"),
        "docs": counts.get("docs"),
        "vectors": counts.get("vectors"),
        "embedding_model": emb_model,
        "embedding_dim": emb_dim,
        "embedding_normalized": emb_norm,
        "has_faiss": (packet_root / "faiss" / "index.faiss").exists(),
        "has_docs": (packet_root / "docs.jsonl").exists(),
        "has_manifest": (packet_root / "manifest.json").exists(),
        "has_cpm_yml": (packet_root / "cpm.yml").exists(),
    }


def _iter_packet_dirs(cpm_dir: Path) -> List[Path]:
    if not cpm_dir.exists() or not cpm_dir.is_dir():
        return []
    out: List[Path] = []
    for p in sorted(cpm_dir.iterdir()):
        if not p.is_dir():
            continue
        if (p / "manifest.json").exists() or (p / "cpm.yml").exists() or (p / "faiss" / "index.faiss").exists():
            out.append(p)
    return out


# ----------------------------
# Helpers (query)
# ----------------------------
import re
from functools import lru_cache


# ============================================================
# Version handling (flexible + strong ordering) - COPIED FROM cpm_pkg.py
# ============================================================

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


_STAGE_ORDER = {
    "dev": 0, "snapshot": 0, "nightly": 0,
    "a": 10, "alpha": 10,
    "b": 20, "beta": 20,
    "pre": 30, "preview": 30,
    "rc": 40, "candidate": 40,
    "stable": 90, "release": 90, "ga": 90,
    "final": 100,
}


def _split_segment_tokens(seg: str) -> Tuple[str, List[str]]:
    s = (seg or "").strip()
    if "-" not in s:
        return s, []
    parts = [p for p in s.split("-") if p != ""]
    return (parts[0], parts[1:]) if parts else (s, [])


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


def _qualifier_stage_and_num(tokens: List[str]) -> Tuple[int, int, Tuple]:
    if not tokens:
        return (1000, 0, ())

    flat: List[Any] = []
    for t in tokens:
        flat.extend(_tokenize_text_and_int(t))

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


def version_key(v: str):
    v = (v or "").strip()
    segs = [s for s in v.split(".") if s != ""]
    out = []
    for seg in segs:
        base, qual = _split_segment_tokens(seg)
        base_tokens = _tokenize_text_and_int(base)
        stage_rank, stage_num, extra = _qualifier_stage_and_num(qual)
        out.append((base_tokens, stage_rank, stage_num, extra))
    return tuple(out)


# ============================================================
# CPM layout helpers - COPIED FROM cpm_pkg.py
# ============================================================

def packet_root(cpm_dir: Path, name: str) -> Path:
    return cpm_dir / name


def packet_pin_path(cpm_dir: Path, name: str) -> Path:
    return packet_root(cpm_dir, name) / "cpm.yml"


def version_dir(cpm_dir: Path, name: str, version: str) -> Path:
    parts = split_version_parts(version)
    return packet_root(cpm_dir, name).joinpath(*parts)


@lru_cache(maxsize=128)
def get_pinned_version(cpm_dir: Path, name: str) -> Optional[str]:
    yml = _read_simple_yml(packet_pin_path(cpm_dir, name))
    v = (yml.get("version") or "").strip()
    return v or None


def _looks_like_version_dir(p: Path) -> bool:
    return (p / "manifest.json").exists() or (p / "faiss" / "index.faiss").exists()


@lru_cache(maxsize=32)
def installed_versions(cpm_dir: Path, name: str) -> List[str]:
    root = packet_root(cpm_dir, name)
    if not root.exists():
        return []
    found: List[str] = []
    for p in root.rglob("cpm.yml"):
        vd = p.parent
        if not _looks_like_version_dir(vd):
            continue
        meta = _read_simple_yml(p)
        v = (meta.get("version") or "").strip()
        if v:
            found.append(v)
    return sorted(set(found), key=version_key)


def _resolve_packet_dir(cpm_dir: Path, packet: str) -> Optional[Path]:
    p = Path(packet)
    if p.exists() and p.is_dir():
        return p

    name = packet
    pinned = get_pinned_version(cpm_dir, name)
    if pinned:
        vd = version_dir(cpm_dir, name, pinned)
        if vd.exists():
            return vd

    vs = installed_versions(cpm_dir, name)
    if not vs:
        return None
    best = max(vs, key=version_key)
    vd = version_dir(cpm_dir, name, best)
    return vd if vd.exists() else None


def _load_docs(docs_path: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    with docs_path.open("r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def _query_packet(
        *,
        cpm_dir: Path,
        packet: str,
        query: str,
        k: int = 5,
        embed_url: Optional[str] = None,
) -> Dict[str, Any]:
    # Lazy imports: costosi
    import faiss  # type: ignore

    from rag.embedding.http_embedder import HttpEmbedder  # local import

    packet_dir = _resolve_packet_dir(cpm_dir, packet)
    if packet_dir is None:
        tried = (cpm_dir / packet).resolve()
        return {
            "ok": False,
            "error": "packet_not_found",
            "packet": packet,
            "tried": str(tried).replace("\\", "/"),
        }

    comp = packet_dir

    manifest = json.loads((comp / "manifest.json").read_text(encoding="utf-8"))
    model_name = manifest["embedding"]["model"]
    max_seq_length = int(manifest["embedding"].get("max_seq_length", 1024))

    docs = _load_docs(comp / "docs.jsonl")
    index = faiss.read_index(str(comp / "faiss" / "index.faiss"))

    if not embed_url:
        embed_url = os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8876")

    client = HttpEmbedder(embed_url)
    if not client.health():
        return {
            "ok": False,
            "error": "embed_server_unreachable",
            "embed_url": embed_url,
            "hint": "start it with: rag cpm embed start-server --detach (or set RAG_EMBED_URL)",
        }

    q = client.embed_texts(
        [query],
        model_name=model_name,
        max_seq_length=max_seq_length,
        normalize=True,
        dtype="float32",
        show_progress=False,
    )

    scores, ids = index.search(q, int(k))
    scores, ids = scores[0], ids[0]

    results: List[Dict[str, Any]] = []
    for idx, sc in zip(ids, scores):
        if int(idx) < 0:
            continue
        d = docs[int(idx)]
        results.append(
            {
                "score": float(sc),
                "id": d.get("id"),
                "text": d.get("text"),
                "metadata": d.get("metadata", {}),
            }
        )

    return {
        "ok": True,
        "packet": comp.name,
        "packet_path": str(comp).replace("\\", "/"),
        "query": query,
        "k": int(k),
        "embedding": {
            "model": model_name,
            "max_seq_length": max_seq_length,
            "embed_url": embed_url,
        },
        "results": results,
    }


# ----------------------------
# MCP Tools
# ----------------------------

@mcp.tool()
def lookup(cpm_dir: str | None = None) -> Dict[str, Any]:
    if not cpm_dir:
        cpm_dir = os.environ.get("RAG_CPM_DIR", ".cpm")

    """
    List installed context packets in a CPM folder (default: .cpm).

    Returns:
      { ok: bool, cpm_dir: str, packets: [ {name, version, ...} ] }
    """
    root = Path(cpm_dir)
    packet_dirs = _iter_packet_dirs(root)
    infos = [_extract_packet_info(p) for p in packet_dirs]
    return {
        "ok": True,
        "cpm_dir": str(root.resolve()).replace("\\", "/"),
        "packets": infos,
        "count": len(infos),
    }


@mcp.tool()
def query(
        packet: str,
        query: str,
        k: int = 5,
        cpm_dir: str | None = None,
        embed_url: Optional[str] = None,
) -> Dict[str, Any]:
    if not cpm_dir:
        cpm_dir = os.environ.get("RAG_CPM_DIR", ".cpm")

    """
    Query an installed packet by name/path under .cpm/ (FAISS + embedding server).

    Params:
      - packet: packet folder name under cpm_dir OR a direct path to a packet folder
      - query: text query
      - k: top-k
      - cpm_dir: CPM root (default: .cpm)
      - embed_url: override embedding server URL (default uses env RAG_EMBED_URL or http://127.0.0.1:8765)
    """
    return _query_packet(
        cpm_dir=Path(cpm_dir),
        packet=packet,
        query=query,
        k=k,
        embed_url=embed_url,
    )


def main() -> None:
    # stdio transport by default
    mcp.run()


if __name__ == "__main__":
    main()
