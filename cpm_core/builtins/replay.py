"""Replay deterministic query logs for auditability."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from cpm_core.api import cpmcommand

from .commands import _WorkspaceAwareCommand
from .query import QueryCommand


@cpmcommand(name="replay", group="cpm")
class ReplayCommand(_WorkspaceAwareCommand):
    """Replay a query execution log and verify output hash deterministically."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("log", help="Path to replay log JSON")
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    def run(self, argv: Any) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        log_path = Path(str(argv.log))
        if not log_path.exists():
            print(f"[cpm:replay] log not found: {log_path}")
            return 1
        payload = self._load_replay_payload(log_path)
        if payload is None:
            return 1
        expected_hash = str(payload.get("output_hash") or "").strip()

        query_command = QueryCommand()
        query_command.workspace_root = workspace_root
        entry = query_command._resolve_retriever_entry(  # noqa: SLF001
            query_command._load_retriever_entries(workspace_root),  # noqa: SLF001
            "native-retriever",
        )
        if entry is None:
            print("[cpm:replay] native retriever not available")
            return 1
        replay_result = query_command._invoke_retriever(  # noqa: SLF001
            entry=entry,
            packet=str(payload.get("packet") or ""),
            query=str(payload.get("query") or ""),
            k=int(payload.get("k") or 5),
            cpm_dir=workspace_root,
            embed_url=None,
            embed_mode=None,
            indexer=str(payload.get("indexer") or "faiss-flatip"),
            reranker=str(payload.get("reranker") or "none"),
            selected_model=str(payload.get("selected_model") or "") or None,
            max_context_tokens=6000,
        )
        actual_hash = str(replay_result.get("output_hash") or "").strip()
        if not actual_hash:
            print("[cpm:replay] replay did not produce output hash")
            return 1
        ok = actual_hash == expected_hash
        response = {
            "ok": ok,
            "expected_hash": expected_hash,
            "actual_hash": actual_hash,
            "packet": payload.get("packet"),
            "query": payload.get("query"),
        }
        if getattr(argv, "format", "text") == "json":
            print(json.dumps(response, indent=2, ensure_ascii=False))
            return 0 if ok else 1
        print(f"[cpm:replay] expected={expected_hash}")
        print(f"[cpm:replay] actual={actual_hash}")
        print(f"[cpm:replay] status={'ok' if ok else 'mismatch'}")
        return 0 if ok else 1

    @staticmethod
    def _load_replay_payload(log_path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[cpm:replay] invalid log payload: {exc}")
            return None
        if not isinstance(payload, dict):
            print("[cpm:replay] log payload must be an object")
            return None
        expected_hash = str(payload.get("output_hash") or "").strip()
        if not expected_hash:
            print("[cpm:replay] log missing output_hash")
            return None
        return payload
