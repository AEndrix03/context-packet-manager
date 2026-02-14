"""Packet semantic diff and drift report."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import numpy as np

from cpm_builtin.packages import PackageManager, parse_package_spec
from cpm_builtin.packages.layout import version_dir
from cpm_core.api import cpmcommand

from .commands import _WorkspaceAwareCommand


@cpmcommand(name="diff", group="cpm")
class DiffCommand(_WorkspaceAwareCommand):
    """Diff packet versions and estimate semantic embedding drift."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("left", help="Left packet ref (name@version or path)")
        parser.add_argument("right", help="Right packet ref (name@version or path)")
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument("--max-drift", type=float, help="Fail if drift score exceeds threshold")
        parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    def run(self, argv: Any) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        left_dir = self._resolve_packet_dir(workspace_root, str(argv.left))
        right_dir = self._resolve_packet_dir(workspace_root, str(argv.right))
        if left_dir is None or right_dir is None:
            print("[cpm:diff] unable to resolve one or both packet references")
            return 1

        left_docs = _load_docs(left_dir / "docs.jsonl")
        right_docs = _load_docs(right_dir / "docs.jsonl")
        left_map = {
            str(item.get("id") or f"idx:{idx}"): str(item.get("text") or "")
            for idx, item in enumerate(left_docs)
        }
        right_map = {
            str(item.get("id") or f"idx:{idx}"): str(item.get("text") or "")
            for idx, item in enumerate(right_docs)
        }

        left_ids = set(left_map)
        right_ids = set(right_map)
        added = sorted(right_ids - left_ids)
        removed = sorted(left_ids - right_ids)
        changed = sorted(doc_id for doc_id in left_ids & right_ids if left_map[doc_id] != right_map[doc_id])

        drift_score = _embedding_drift(left_dir / "vectors.f16.bin", right_dir / "vectors.f16.bin")
        denominator = max(len(left_ids | right_ids), 1)
        delta_ndcg_proxy = round((len(changed) + len(added) + len(removed)) / denominator, 6)

        report = {
            "ok": True,
            "left": str(left_dir),
            "right": str(right_dir),
            "added": added,
            "removed": removed,
            "changed": changed,
            "drift_score": drift_score,
            "delta_ndcg_proxy": delta_ndcg_proxy,
        }
        threshold = getattr(argv, "max_drift", None)
        if threshold is not None and drift_score is not None and drift_score > float(threshold):
            report["ok"] = False
            report["error"] = "drift_threshold_exceeded"

        if getattr(argv, "format", "text") == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report.get("ok", True) else 1

        print(f"[cpm:diff] left={left_dir}")
        print(f"[cpm:diff] right={right_dir}")
        print(f"[cpm:diff] added={len(added)} removed={len(removed)} changed={len(changed)}")
        print(f"[cpm:diff] drift_score={drift_score} delta_ndcg_proxy={delta_ndcg_proxy}")
        if not report.get("ok", True):
            print(f"[cpm:diff] error={report.get('error')}")
            return 1
        return 0

    @staticmethod
    def _resolve_packet_dir(workspace_root: Path, packet: str) -> Path | None:
        candidate = Path(packet)
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
        manager = PackageManager(workspace_root)
        name, explicit_version = parse_package_spec(packet)
        if not name:
            return None
        try:
            resolved = manager.resolve_version(name, explicit_version)
        except ValueError:
            return None
        target = version_dir(workspace_root, name, resolved)
        if not target.exists():
            return None
        return target.resolve()


def _load_docs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    docs: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                docs.append(payload)
    return docs


def _embedding_drift(left_path: Path, right_path: Path) -> float | None:
    if not left_path.exists() or not right_path.exists():
        return None
    left = np.fromfile(left_path, dtype=np.float16)
    right = np.fromfile(right_path, dtype=np.float16)
    if left.size == 0 or right.size == 0:
        return None
    size = min(left.size, right.size)
    delta = left[:size].astype(np.float32) - right[:size].astype(np.float32)
    return float(np.linalg.norm(delta) / max(size, 1))
