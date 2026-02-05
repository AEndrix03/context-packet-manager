from __future__ import annotations

import hashlib
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from cli.core.client import (
    RegistryClient,
    RegistryPackageList,
    RegistryPackageVersion,
)


# ============================================================
# Version handling (flexible + strong ordering)
# ============================================================

def _safe_segment(seg: str) -> str:
    """
    Make a single path segment safe (no remap).
    - no slashes/backslashes
    - keep readable
    """
    s = (seg or "").strip()
    if not s:
        return ""
    s = s.replace("\\", "/").replace("/", "-")
    # Do NOT change dots here; dots are separators at version split stage
    s = re.sub(r"[^a-zA-Z0-9._\-+@]+", "-", s).strip("-")
    return s


def split_version_parts(version: str) -> List[str]:
    """
    Split version string into path parts by '.' (no remap).
    Examples:
      - "0.1.2.5-beta.4.5" => ["0","1","2","5-beta","4","5"]
      - "1" => ["1"]
    """
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


# ---- precedence model (lower = earlier/less stable) ----
# You can extend this list anytime.
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

    # "stable/final" are "no prerelease" ideally, but allow explicit tags:
    "stable": 90,
    "release": 90,
    "ga": 90,

    "final": 100,
}


# If you want to treat explicit "latest" tag inside version (rare) as highest, enable:
# But generally "@latest" is the alias, not a tag inside version.
# _STAGE_ORDER["latest"] = 1000


def _split_segment_tokens(seg: str) -> Tuple[str, List[str]]:
    """
    Split a segment into base + qualifiers by '-'.
      "5-beta-2" => base="5", qualifiers=["beta","2"]
      "rc1"      => base="rc1", qualifiers=[]  (handled later)
    """
    s = (seg or "").strip()
    if "-" not in s:
        return s, []
    parts = [p for p in s.split("-") if p != ""]
    if not parts:
        return s, []
    return parts[0], parts[1:]


def _tokenize_text_and_int(s: str) -> List[Any]:
    """
    Tokenize a string into a list of (type, value) where type 0=int, 1=str.
    Examples:
      "rc10" -> [ (1,"rc"), (0,10) ]
      "beta2"-> [ (1,"beta"), (0,2) ]
      "foo"  -> [ (1,"foo") ]
      "12"   -> [ (0,12) ]
    """
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
    """
    Convert qualifier tokens into a comparable triple:
      - stage_rank (bigger = more stable)
      - stage_num (bigger = later within same stage)
      - extra tokens (fallback)
    Rules:
      - no qualifiers => treat as implicit stable/final (highest) => stage_rank=1000
      - first textual token in qualifiers decides stage if known
      - numeric tokens after stage increase stage_num
      - unknown text tokens: treated as stage_rank=50 (mid), but ordered lexicographically
    """
    if not tokens:
        # No prerelease => highest
        return (1000, 0, ())

    # flatten tokens (including rc10 etc)
    flat: List[Any] = []
    for t in tokens:
        flat.extend(_tokenize_text_and_int(t))

    stage_rank = None
    stage_num = 0
    extra: List[Any] = []

    # find first stage token (string)
    for typ, val in flat:
        if typ == 1:
            if val in _STAGE_ORDER:
                stage_rank = _STAGE_ORDER[val]
                continue
            # allow rc10 style: val might be "rc" already from tokenizer
            # if unknown, keep as extra
            extra.append((typ, val))
        else:
            # ints that appear before stage are treated as extra
            extra.append((typ, val))

        if stage_rank is not None:
            break

    if stage_rank is None:
        # unknown prerelease => place between rc and stable-ish
        stage_rank = 50

    # stage_num: sum of ints in flat after we have a stage
    seen_stage = False
    for typ, val in flat:
        if typ == 1 and val in _STAGE_ORDER and not seen_stage:
            seen_stage = True
            continue
        if seen_stage and typ == 0:
            stage_num = val
            break

    # remaining tokens become extra ordering
    # (so beta.1 < beta.2, and beta.2-foo is deterministic)
    return (stage_rank, stage_num, tuple(extra))


def _cmp_tokens(a: List[Any], b: List[Any]) -> int:
    """
    Compare lists of (type,value) tokens.
    int tokens compare numerically; str tokens lexicographically.
    int tokens considered > str tokens at same position.
    """
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
            # int (0) > str (1)
            return 1 if ta < tb else -1
        if va == vb:
            continue
        return 1 if va > vb else -1
    return 0


def compare_versions(a: str, b: str) -> int:
    """
    Strong-ish ordering:
    - compare by dot segments, left->right
    - each segment: compare base tokens (ints/strings)
    - then compare prerelease qualifiers:
        no qualifier > stable/final tags > rc > beta > alpha > dev
    - if equal so far: longer version (more segments) is considered greater
    """
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

        # base equal -> compare qualifier stability
        stage_a = _qualifier_stage_and_num(qual_a)
        stage_b = _qualifier_stage_and_num(qual_b)
        if stage_a != stage_b:
            return 1 if stage_a > stage_b else -1

    # all segments equal length-wise and content-wise
    # if same segments count already handled; otherwise handled above
    return 0


def version_key(v: str):
    # Python key: use tuple of comparable objects by normalizing compare into key
    # We can't directly use compare function as key; so we build a deterministic key.
    # We'll map each segment into tokens.
    v = (v or "").strip()
    segs = [s for s in v.split(".") if s != ""]
    out = []
    for seg in segs:
        base, qual = _split_segment_tokens(seg)
        base_tokens = _tokenize_text_and_int(base)
        stage_rank, stage_num, extra = _qualifier_stage_and_num(qual)
        # Note: higher is better, so keep stage_rank/stage_num as is
        out.append((base_tokens, stage_rank, stage_num, extra))
    return tuple(out)


def registry_latest_version(client: RegistryClient, name: str) -> str:
    """
    Latest = max by semantic ordering (NOT by published_at).
    """
    data = client.list(name, include_yanked=False)
    if not data.versions:
        raise RuntimeError(f"no versions found on registry for {name}")

    vs = [v.version for v in data.versions if v.version]
    if not vs:
        raise RuntimeError(f"no valid versions found on registry for {name}")

    return max(vs, key=version_key)


# ============================================================
# Minimal YAML (key: value)
# ============================================================

def read_simple_yml(path: Path) -> Dict[str, str]:
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


def write_simple_yml(path: Path, kv: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(kv.keys())
    lines = []
    for k in keys:
        v = kv[k]
        if any(ch in v for ch in [":", "#", "\n", "\r", "\t"]):
            v = v.replace('"', '\\"')
            v = f"\"{v}\""
        lines.append(f"{k}: {v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================================
# CPM layout helpers
# ============================================================

REQUIRED_ARTIFACTS = [
    "manifest.json",
    "vectors.f16.bin",
    "docs.jsonl",
    "cpm.yml",
    os.path.join("faiss", "index.faiss"),
]


def verify_built_packet_dir(src_dir: Path) -> None:
    missing = []
    for rel in REQUIRED_ARTIFACTS:
        if not (src_dir / rel).exists():
            missing.append(rel)
    if missing:
        raise FileNotFoundError(f"missing required artifacts in {src_dir}: {', '.join(missing)}")


def read_built_meta(src_dir: Path) -> Tuple[str, str]:
    yml = read_simple_yml(src_dir / "cpm.yml")
    name = (yml.get("name") or "").strip()
    version = (yml.get("version") or "").strip()
    if not name or not version:
        raise ValueError("cpm.yml missing required fields: name, version")
    # validate only for non-empty and path-splittable
    split_version_parts(version)
    return name, version


def packet_root(cpm_dir: Path, name: str) -> Path:
    return cpm_dir / name


def packet_pin_path(cpm_dir: Path, name: str) -> Path:
    return packet_root(cpm_dir, name) / "cpm.yml"


def version_dir(cpm_dir: Path, name: str, version: str) -> Path:
    parts = split_version_parts(version)
    return packet_root(cpm_dir, name).joinpath(*parts)


def get_pinned_version(cpm_dir: Path, name: str) -> Optional[str]:
    yml = read_simple_yml(packet_pin_path(cpm_dir, name))
    v = (yml.get("version") or "").strip()
    return v or None


def set_pinned_version(cpm_dir: Path, name: str, version: str) -> None:
    split_version_parts(version)
    pin = packet_pin_path(cpm_dir, name)
    kv = read_simple_yml(pin)
    kv["name"] = name
    kv["version"] = version
    write_simple_yml(pin, kv)


def _looks_like_version_dir(p: Path) -> bool:
    return (p / "manifest.json").exists() or (p / "faiss" / "index.faiss").exists()


def installed_versions(cpm_dir: Path, name: str) -> List[str]:
    """
    Return installed versions by reading version from each version dir's cpm.yml.
    """
    root = packet_root(cpm_dir, name)
    if not root.exists():
        return []

    found: List[str] = []
    for p in root.rglob("cpm.yml"):
        vd = p.parent
        if not _looks_like_version_dir(vd):
            continue
        meta = read_simple_yml(p)
        v = (meta.get("version") or "").strip()
        if v:
            found.append(v)

    # unique + sort by semantic key
    return sorted(set(found), key=version_key)


def resolve_current_packet_dir(cpm_dir: Path, packet: str) -> Optional[Path]:
    """
    Resolve packet argument:
      - direct path => used as-is
      - name => use .cpm/<name>/cpm.yml 'version' if present
      - fallback => pick max among installed versions (semantic max)
    """
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


# ============================================================
# Tar helpers (publish/install)
# ============================================================

def _safe_tar_extract(tf: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for m in tf.getmembers():
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(dest) + os.sep) and target != dest:
            raise RuntimeError(f"unsafe tar member path: {m.name}")
    tf.extractall(dest)


def _sha256_file(path: Path) -> str:
    hash_obj = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def _verify_tarball(path: Path, metadata: RegistryPackageVersion) -> None:
    if metadata.sha256:
        actual = _sha256_file(path)
        if actual != metadata.sha256:
            raise RuntimeError(
                f"tarball checksum mismatch for {metadata.name}@{metadata.version}: "
                f"expected {metadata.sha256} but got {actual}"
            )
    if metadata.size_bytes is not None:
        actual_size = path.stat().st_size
        if actual_size != metadata.size_bytes:
            raise RuntimeError(
                f"tarball size mismatch for {metadata.name}@{metadata.version}: "
                f"expected {metadata.size_bytes} bytes but got {actual_size}"
            )


def _extract_version_from_tar(
    tar_path: Path, staging: Path, cpm_dir: Path, name: str, version: str
) -> Path:
    with tarfile.open(tar_path, "r:gz") as tf:
        _safe_tar_extract(tf, staging)

    extracted = staging.joinpath(name, *split_version_parts(version))
    if not extracted.exists():
        raise RuntimeError(f"extracted payload missing for {name}@{version}")

    final_dir = version_dir(cpm_dir, name, version)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    shutil.move(str(extracted), str(final_dir))
    return final_dir


def make_versioned_tar_from_build_dir(src_dir: Path, name: str, version: str, out_path: Path) -> None:
    """
    Create tar.gz with layout:
      <name>/<version_parts...>/...  (version parts are split by '.')
    """
    parts = split_version_parts(version)

    if out_path.exists():
        out_path.unlink()

    with tempfile.TemporaryDirectory(prefix="cpm-publish-") as tmpd:
        tmp = Path(tmpd)
        root = tmp / name
        ver_root = root.joinpath(*parts)
        ver_root.mkdir(parents=True, exist_ok=True)

        for p in src_dir.iterdir():
            if p.is_file() and p.name.endswith((".tar.gz", ".zip")):
                continue
            dst = ver_root / p.name
            if p.is_dir():
                shutil.copytree(p, dst)
            else:
                shutil.copy2(p, dst)

        with tarfile.open(out_path, "w:gz") as tf:
            tf.add(root, arcname=name)


def download_and_extract(client: RegistryClient, name: str, version: str, cpm_dir: Path) -> Path:
    """
    Download tar and extract into cpm_dir. Returns extracted version directory path.
    """
    cpm_dir.mkdir(parents=True, exist_ok=True)
    metadata = client.get_version(name, version)

    with tempfile.TemporaryDirectory(prefix="cpm-install-") as tmpd:
        tmp = Path(tmpd)
        tar_path = tmp / f"{name}-{version}.tar.gz"
        client.download(name, version, str(tar_path))
        _verify_tarball(tar_path, metadata)
        return _extract_version_from_tar(tar_path, tmp, cpm_dir, name, version)
