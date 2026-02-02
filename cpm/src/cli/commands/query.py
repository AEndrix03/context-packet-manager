import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import faiss

from cli.core.cpm_pkg import resolve_current_packet_dir
from embedding.http_embedder import HttpEmbedder


def load_docs(docs_path: Path):
    docs = []
    with docs_path.open("r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


# -----------------------------
# Packet resolve (versioned)
# -----------------------------

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _packet_has_artifacts(p: Path) -> bool:
    return (
            (p / "manifest.json").exists()
            and (p / "docs.jsonl").exists()
            and (p / "faiss" / "index.faiss").exists()
    )


def _resolve_latest_versioned_dir(packet_root: Path) -> Optional[Path]:
    """
    packet_root = .cpm/<name>
    cerca .cpm/<name>/<x>/<y>/<z> con manifest.json e index.faiss.
    seleziona la versione più alta.
    """
    if not packet_root.exists() or not packet_root.is_dir():
        return None

    # Se già è un packet root "flat"
    if _packet_has_artifacts(packet_root):
        return packet_root

    best: Optional[Tuple[int, int, int]] = None
    best_dir: Optional[Path] = None

    for major_dir in packet_root.iterdir():
        if not major_dir.is_dir() or not major_dir.name.isdigit():
            continue
        for minor_dir in major_dir.iterdir():
            if not minor_dir.is_dir() or not minor_dir.name.isdigit():
                continue
            for patch_dir in minor_dir.iterdir():
                if not patch_dir.is_dir() or not patch_dir.name.isdigit():
                    continue
                if not _packet_has_artifacts(patch_dir):
                    continue
                v = (int(major_dir.name), int(minor_dir.name), int(patch_dir.name))
                if best is None or v > best:
                    best = v
                    best_dir = patch_dir

    return best_dir


def _resolve_packet_dir(cpm_dir: Path, packet: str) -> Path | None:
    """
    Supporta:
      - path diretto a packet root
      - .cpm/<name> (legacy flat)
      - .cpm/<name>/<major>/<minor>/<patch> (versioned) => sceglie latest
    """
    packet_arg = Path(packet)
    if packet_arg.exists() and packet_arg.is_dir():
        if _packet_has_artifacts(packet_arg):
            return packet_arg
        # se mi passi direttamente .cpm/<name>, provo latest
        latest = _resolve_latest_versioned_dir(packet_arg)
        return latest

    candidate = cpm_dir / packet
    if candidate.exists() and candidate.is_dir():
        if _packet_has_artifacts(candidate):
            return candidate
        latest = _resolve_latest_versioned_dir(candidate)
        if latest is not None:
            return latest

    return None


# -----------------------------
# Cache (phase 0)
# -----------------------------

CACHE_SCHEMA_VERSION = 1


def _canonicalize_query_args(args, *, packet_dir: Path, model_name: str, max_seq_length: int) -> Dict[str, Any]:
    """
    Canonical dict per hash stabile.
    Include solo ciò che cambia effettivamente l'output.
    """
    return {
        "cmd": "cpm.query",
        "packet_arg": str(args.packet),
        "packet_dir": str(packet_dir).replace("\\", "/"),
        "query": (args.query or "").strip(),
        "k": int(args.k),
        "cpm_dir": str(args.cpm_dir).replace("\\", "/"),
        "embedding_model": model_name,
        "max_seq_length": int(max_seq_length),
        "normalize": True,
        "schema_version": CACHE_SCHEMA_VERSION,
    }


def _stable_sha256(obj: Dict[str, Any]) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _history_dir(packet_dir: Path) -> Path:
    # cache dentro la versione del packet
    return packet_dir / ".history" / f"v{CACHE_SCHEMA_VERSION}"


def _cache_path(packet_dir: Path, cache_key: str) -> Path:
    return _history_dir(packet_dir) / f"{cache_key}.json"


def _cache_load(packet_dir: Path, cache_key: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(packet_dir, cache_key)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _cache_store(packet_dir: Path, cache_key: str, record: Dict[str, Any]) -> None:
    d = _history_dir(packet_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = _cache_path(packet_dir, cache_key)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _print_results(header: str, query: str, k: int, packet_name: str, results: List[Dict[str, Any]]) -> None:
    print(f"{header} '{query}' (k={k}) packet={packet_name}")
    for r in results:
        rank = r.get("rank")
        sc = r.get("score")
        doc = r.get("doc") or {}
        meta = (doc.get("metadata") or {})
        print(f"\n#{rank} score={float(sc):.4f} id={doc.get('id')}")
        if meta.get("path"):
            print(f"   path={meta['path']} lines={meta.get('line_start')}-{meta.get('line_end')}")
        print(doc.get("text", ""))


# -----------------------------
# Main command
# -----------------------------

def cmd_query(args) -> None:
    cpm_dir = Path(args.cpm_dir)
    packet_dir = resolve_current_packet_dir(cpm_dir, args.packet)

    if packet_dir is None:
        tried = (cpm_dir / args.packet).resolve()
        print(f"[cpm:query] packet not found: {args.packet}")
        print(f"           tried: {tried}")
        return

    comp = packet_dir

    manifest = json.loads((comp / "manifest.json").read_text(encoding="utf-8"))
    model_name = manifest["embedding"]["model"]
    max_seq_length = int(manifest["embedding"].get("max_seq_length", 1024))

    # cache flags
    use_cache = not getattr(args, "no_cache", False)
    refresh_cache = getattr(args, "cache_refresh", False)
    if getattr(args, "no_cache", False) and getattr(args, "cache_refresh", False):
        print("[cpm:query] warning: --no-cache overrides --cache-refresh")

    # ---- cache lookup (prima di caricare docs/faiss/embed)
    canon = _canonicalize_query_args(args, packet_dir=comp, model_name=model_name, max_seq_length=max_seq_length)
    cache_key = _stable_sha256(canon)

    if use_cache and not refresh_cache:
        cached = _cache_load(comp, cache_key)
        if cached is not None:
            payload = cached.get("payload") or {}
            results = payload.get("results") or []
            _print_results("[cpm:query][cache-hit]", canon["query"], canon["k"], comp.name, results)
            return

    # ---- cache miss: esegui davvero
    docs = load_docs(comp / "docs.jsonl")
    index = faiss.read_index(str(comp / "faiss" / "index.faiss"))

    embed_url = os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8876")
    client = HttpEmbedder(embed_url)

    if not client.health():
        print(f"[error] embedding server not reachable at {embed_url}")
        print("        - start it with: rag cpm embed start-server --detach")
        print("        - or set RAG_EMBED_URL")
        return

    q = client.embed_texts(
        [canon["query"]],
        model_name=model_name,
        max_seq_length=max_seq_length,
        normalize=True,
        dtype="float32",
        show_progress=False,
    )

    scores, ids = index.search(q, int(args.k))
    scores, ids = scores[0], ids[0]

    results: List[Dict[str, Any]] = []
    rank = 0
    for idx, sc in zip(ids, scores):
        if idx < 0:
            continue
        rank += 1
        d = docs[int(idx)]
        results.append(
            {
                "rank": rank,
                "score": float(sc),
                "faiss_idx": int(idx),
                "doc": d,
            }
        )

    tag = "[cpm:query]"
    if refresh_cache:
        tag = "[cpm:query][cache-refresh]"
    elif not use_cache:
        tag = "[cpm:query][no-cache]"

    _print_results(tag, canon["query"], canon["k"], comp.name, results)

    # ---- store cache record (phase 0: no vectors)
    if use_cache:
        record = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cache_key": f"sha256:{cache_key}",
            "command": {
                "args_canonical": canon
            },
            "environment": {
                "packet_dir": str(comp).replace("\\", "/"),
            },
            "payload": {
                "results": results,
                "query_vec": None,
                "result_vecs": None,
            },
        }
        _cache_store(comp, cache_key, record)
