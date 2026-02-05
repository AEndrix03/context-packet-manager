"""Helper that inspects context packet directories."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_STAGE_ORDER = {
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


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _read_simple_yml(path: Path) -> Dict[str, str]:
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


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_segment(seg: str) -> str:
    value = (seg or "").strip()
    if not value:
        return ""
    value = value.replace("\\", "/").replace("/", "-")
    value = re.sub(r"[^a-zA-Z0-9._\\-+@]+", "-", value).strip("-")
    return value


def split_version_parts(version: str) -> List[str]:
    v = (version or "").strip()
    if not v:
        raise ValueError("empty version")
    raw = v.split(".")
    parts = [_safe_segment(part) for part in raw if part is not None and part != ""]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError(f"invalid version after sanitization: {version!r}")
    return parts


def _split_segment_tokens(seg: str) -> Tuple[str, List[str]]:
    value = (seg or "").strip()
    if "-" not in value:
        return value, []
    parts = [part for part in value.split("-") if part != ""]
    return (parts[0], parts[1:]) if parts else (value, [])


def _tokenize_text_and_int(segment: str) -> List[Any]:
    value = (segment or "").strip()
    if not value:
        return []
    out: List[Any] = []
    i = 0
    while i < len(value):
        if value[i].isdigit():
            j = i
            while j < len(value) and value[j].isdigit():
                j += 1
            out.append((0, int(value[i:j])))
            i = j
        else:
            j = i
            while j < len(value) and not value[j].isdigit():
                j += 1
            out.append((1, value[i:j].lower()))
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

    for typ, value in flat:
        if typ == 1:
            if value in _STAGE_ORDER:
                stage_rank = _STAGE_ORDER[value]
                continue
            extra.append((typ, value))
        else:
            extra.append((typ, value))
        if stage_rank is not None:
            break

    if stage_rank is None:
        stage_rank = 50

    seen_stage = False
    for typ, value in flat:
        if typ == 1 and value in _STAGE_ORDER and not seen_stage:
            seen_stage = True
            continue
        if seen_stage and typ == 0:
            stage_num = value
            break

    return (stage_rank, stage_num, tuple(extra))


def version_key(version: str) -> Tuple[Tuple[List[Any], int, int, Tuple[Any, ...]], ...]:
    normalized = (version or "").strip()
    segments = [segment for segment in normalized.split(".") if segment != ""]
    out: List[Tuple[List[Any], int, int, Tuple[Any, ...]]] = []
    for segment in segments:
        base, qualifiers = _split_segment_tokens(segment)
        base_tokens = _tokenize_text_and_int(base)
        stage_rank, stage_num, extra = _qualifier_stage_and_num(qualifiers)
        out.append((base_tokens, stage_rank, stage_num, extra))
    return tuple(out)


def _looks_like_version_dir(path: Path) -> bool:
    return (path / "manifest.json").exists() or (path / "faiss" / "index.faiss").exists()


class PacketReader:
    """Inspect packets inside a CPM workspace."""

    def __init__(self, cpm_dir: Path):
        self.root = cpm_dir

    def list_packets(self, *, include_all_versions: bool = False) -> List[Dict[str, Any]]:
        if include_all_versions:
            dirs = self._iter_packet_dirs()
        else:
            dirs = self._current_packet_dirs()
        return [self._extract_packet_info(path) for path in dirs]

    def resolve_packet_dir(self, packet: str) -> Optional[Path]:
        candidate = Path(packet)
        if candidate.exists() and candidate.is_dir():
            return candidate

        pinned = self._get_pinned_version(packet)
        if pinned:
            target = self._version_dir(packet, pinned)
            if target.exists():
                return target

        versions = self._installed_versions(packet)
        if not versions:
            return None
        best = max(versions, key=version_key)
        target = self._version_dir(packet, best)
        return target if target.exists() else None

    def _current_packet_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        if not self.root.exists():
            return dirs
        for name_dir in sorted(self.root.iterdir()):
            if not name_dir.is_dir():
                continue
            name = name_dir.name
            pinned = self._get_pinned_version(name)
            if pinned:
                version_dir = self._version_dir(name, pinned)
                if version_dir.exists():
                    dirs.append(version_dir)
                    continue
            versions = self._installed_versions(name)
            if not versions:
                continue
            best = max(versions, key=version_key)
            version_dir = self._version_dir(name, best)
            if version_dir.exists():
                dirs.append(version_dir)
        return dirs

    def _iter_packet_dirs(self) -> List[Path]:
        out: List[Path] = []
        if not self.root.exists() or not self.root.is_dir():
            return out

        def is_packet_root(path: Path) -> bool:
            return (
                (path / "manifest.json").exists()
                or (path / "cpm.yml").exists()
                or (path / "faiss" / "index.faiss").exists()
            )

        for name_dir in sorted(self.root.iterdir()):
            if not name_dir.is_dir():
                continue
            if is_packet_root(name_dir):
                out.append(name_dir)
                continue
            for candidate in name_dir.rglob("*"):
                if not candidate.is_dir():
                    continue
                if candidate.name == ".history":
                    continue
                if candidate == name_dir:
                    continue
                if is_packet_root(candidate):
                    out.append(candidate)

        unique: List[Path] = []
        seen: set[str] = set()
        for path in out:
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def _packet_root(self, name: str) -> Path:
        return self.root / name

    def _version_dir(self, name: str, version: str) -> Path:
        parts = split_version_parts(version)
        return self._packet_root(name).joinpath(*parts)

    def _packet_pin_path(self, name: str) -> Path:
        return self._packet_root(name) / "cpm.yml"

    @lru_cache(maxsize=128)
    def _get_pinned_version(self, name: str) -> Optional[str]:
        data = _read_simple_yml(self._packet_pin_path(name))
        version = (data.get("version") or "").strip()
        return version or None

    @lru_cache(maxsize=32)
    def _installed_versions(self, name: str) -> List[str]:
        root = self._packet_root(name)
        if not root.exists():
            return []
        versions: List[str] = []
        for path in root.rglob("cpm.yml"):
            version_dir = path.parent
            if not _looks_like_version_dir(version_dir):
                continue
            meta = _read_simple_yml(path)
            version = (meta.get("version") or "").strip()
            if version:
                versions.append(version)
        return sorted(set(versions), key=version_key)

    def _extract_packet_info(self, packet_root: Path) -> Dict[str, Any]:
        manifest = _read_json(packet_root / "manifest.json") or {}
        yml = _read_simple_yml(packet_root / "cpm.yml")

        name = yml.get("name") or manifest.get("packet_id") or packet_root.name
        version = yml.get("version") or (manifest.get("cpm") or {}).get("version") or "unknown"
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
