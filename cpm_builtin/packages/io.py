"""Minimal YAML helpers for writing simple key-value files."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

__all__ = ["read_simple_yml", "write_simple_yml"]


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
    lines: list[str] = []
    for k in keys:
        v = kv[k]
        if any(ch in v for ch in [":", "#", "\n", "\r", "\t"]):
            v = v.replace('"', '\\"')
            v = f'"{v}"'
        lines.append(f"{k}: {v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
