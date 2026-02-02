import json
from pathlib import Path
from typing import Any, Dict, Optional, List

from cli.core.cpm_pkg import (
    get_pinned_version,
    installed_versions,
    version_dir,
    version_key,
)


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
    version = yml.get("version") or (manifest.get("cpm", {}) or {}).get("version") or "unknown"
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

    info: Dict[str, Any] = {
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
    return info


def _iter_packet_dirs(cpm_dir: Path) -> List[Path]:
    """
    Version-agnostic scan.

    Struttura prevista:
      .cpm/<name>/cpm.yml                 (pin file a livello packet)
      .cpm/<name>/<v-part-1>/<v-part-2>/.../<v-part-n>/[manifest.json|faiss/index.faiss|cpm.yml]
    """
    if not cpm_dir.exists() or not cpm_dir.is_dir():
        return []

    out: List[Path] = []

    def is_packet_root(p: Path) -> bool:
        return (
                (p / "manifest.json").exists()
                or (p / "cpm.yml").exists()
                or (p / "faiss" / "index.faiss").exists()
        )

    for name_dir in sorted(cpm_dir.iterdir()):
        if not name_dir.is_dir():
            continue

        # legacy root (se esiste ancora)
        if is_packet_root(name_dir):
            out.append(name_dir)
            continue

        # versioned roots: cerca dirs che contengono artifact
        for p in name_dir.rglob("*"):
            if not p.is_dir():
                continue
            if p.name == ".history":
                continue
            if p == name_dir:
                continue
            if is_packet_root(p):
                out.append(p)

    # dedup
    uniq: List[Path] = []
    seen = set()
    for p in out:
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def cmd_cpm_lookup(args) -> None:
    cpm_dir = Path(args.cpm_dir)

    if getattr(args, "all_versions", False):
        packet_dirs = _iter_packet_dirs(cpm_dir)
    else:
        # current only: per packet scegli pinned o best locale (version_key)
        packet_dirs: List[Path] = []
        if cpm_dir.exists():
            for name_dir in sorted(cpm_dir.iterdir()):
                if not name_dir.is_dir():
                    continue

                name = name_dir.name

                pinned = get_pinned_version(cpm_dir, name)
                if pinned:
                    vd = version_dir(cpm_dir, name, pinned)
                    if vd.exists():
                        packet_dirs.append(vd)
                        continue

                vs = installed_versions(cpm_dir, name)
                best = max(vs, key=version_key) if vs else None
                if best:
                    vd = version_dir(cpm_dir, name, best)
                    if vd.exists():
                        packet_dirs.append(vd)

    if not packet_dirs:
        print(f"[cpm:lookup] No packets found in: {cpm_dir.resolve()}")
        return

    infos = [_extract_packet_info(p) for p in packet_dirs]

    fmt = getattr(args, "format", "text")
    if fmt == "jsonl":
        for info in infos:
            print(json.dumps(info, ensure_ascii=False))
        return

    for info in infos:
        print(f"- {info['name']}@{info['version']}")
        print(f"  path={info['path']}")
        if info.get("description"):
            print(f"  desc={info['description']}")
        if info.get("embedding_model") or info.get("embedding_dim") is not None:
            print(
                f"  embedding={info.get('embedding_model')} "
                f"dim={info.get('embedding_dim')} norm={info.get('embedding_normalized')}"
            )
        if info.get("docs") is not None or info.get("vectors") is not None:
            print(f"  counts docs={info.get('docs')} vectors={info.get('vectors')}")
        print(
            f"  has_faiss={info.get('has_faiss')} has_docs={info.get('has_docs')} "
            f"has_manifest={info.get('has_manifest')} has_cpm_yml={info.get('has_cpm_yml')}"
        )
