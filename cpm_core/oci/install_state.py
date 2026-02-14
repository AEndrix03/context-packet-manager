"""Local install lock helpers for OCI-installed packets."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def install_lock_path(workspace_root: Path, packet_name: str) -> Path:
    return workspace_root / "state" / "install" / f"{packet_name}.lock.json"


def read_install_lock(workspace_root: Path, packet_name: str) -> dict[str, Any] | None:
    path = install_lock_path(workspace_root, packet_name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_install_lock(payload)


def write_install_lock(workspace_root: Path, packet_name: str, payload: dict[str, Any]) -> Path:
    path = install_lock_path(workspace_root, packet_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_lock_snapshot(workspace_root, packet_name, path)
    return path


def read_install_lock_as_of(
    workspace_root: Path,
    packet_name: str,
    *,
    as_of: datetime,
) -> dict[str, Any] | None:
    history_root = workspace_root / "state" / "install" / "history" / packet_name
    if not history_root.exists():
        return None
    target = as_of.astimezone(UTC)
    chosen: Path | None = None
    chosen_ts: datetime | None = None
    for item in history_root.glob("*.lock.json"):
        stamp = _parse_snapshot_timestamp(item.name)
        if stamp is None:
            continue
        if stamp <= target and (chosen_ts is None or stamp > chosen_ts):
            chosen = item
            chosen_ts = stamp
    if chosen is None:
        return None
    try:
        payload = json.loads(chosen.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_install_lock(payload)


def _normalize_install_lock(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if not isinstance(normalized.get("sources"), list):
        packet_ref = str(normalized.get("packet_ref") or "").strip()
        packet_digest = str(normalized.get("packet_digest") or "").strip()
        if packet_ref and packet_digest:
            normalized["sources"] = [
                {
                    "uri": f"oci://{packet_ref}",
                    "digest": packet_digest,
                    "signature": bool(normalized.get("signature", False)),
                    "sbom": bool(normalized.get("sbom", False)),
                    "provenance": bool(normalized.get("provenance", False)),
                    "trust_score": float(normalized.get("trust_score", 0.0)),
                }
            ]
    if "trust_score" not in normalized:
        normalized["trust_score"] = 0.0
    return normalized


def _write_lock_snapshot(workspace_root: Path, packet_name: str, lock_path: Path) -> None:
    history_root = workspace_root / "state" / "install" / "history" / packet_name
    history_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = history_root / f"{stamp}.lock.json"
    shutil.copy2(lock_path, destination)


_STAMP_RE = re.compile(r"^(\d{8}T\d{6}(?:\.\d{6})?Z)\.lock\.json$")


def _parse_snapshot_timestamp(name: str) -> datetime | None:
    match = _STAMP_RE.match(name)
    if not match:
        return None
    try:
        raw = match.group(1)
        fmt = "%Y%m%dT%H%M%SZ" if "." not in raw else "%Y%m%dT%H%M%S.%fZ"
        value = datetime.strptime(raw, fmt)
    except ValueError:
        return None
    return value.replace(tzinfo=UTC)
