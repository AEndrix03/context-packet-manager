from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import cpm_core.builtins.query as query_mod
import cpm_core.builtins.replay as replay_mod
from cpm_cli.main import main as cli_main

SMALL_TOKEN_BUDGET = 12


def test_context_compiler_emits_citations_and_respects_budget() -> None:
    compiled = query_mod._compile_context(  # noqa: SLF001
        query="auth setup",
        hits=[
            {
                "id": "doc-1",
                "score": 0.9,
                "text": "Authentication setup guide for production deployments.",
                "metadata": {"path": "docs/auth.md"},
            },
            {
                "id": "doc-2",
                "score": 0.8,
                "text": "Second snippet that should be excluded by strict token budget.",
                "metadata": {"path": "docs/other.md"},
            },
        ],
        max_tokens=SMALL_TOKEN_BUDGET,
        warnings=[],
    )

    snippets = compiled["core_snippets"]
    assert snippets
    assert all(item.get("citation") for item in snippets)
    assert int(compiled["token_estimate"]) <= SMALL_TOKEN_BUDGET


def test_query_as_of_uses_historical_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))

    history = workspace_root / "state" / "install" / "history" / "demo"
    history.mkdir(parents=True, exist_ok=True)
    (history / "20250101T000000Z.lock.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "selected_model": "model-old"}),
        encoding="utf-8",
    )
    (history / "20260101T000000Z.lock.json").write_text(
        json.dumps({"name": "demo", "version": "2.0.0", "selected_model": "model-new"}),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _fake_retrieve(self, identifier: str, **kwargs):
        del self, identifier
        captured.update(kwargs)
        return {"ok": True, "packet": kwargs.get("packet"), "query": "q", "k": kwargs.get("k", 5), "results": []}

    monkeypatch.setattr(query_mod.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main(
        [
            "query",
            "--packet",
            "demo",
            "--query",
            "auth",
            "--as-of",
            "2025-06-01",
        ],
        start_dir=tmp_path,
    )
    assert code == 0
    assert captured.get("packet") == "demo@1.0.0"


def test_replay_command_validates_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))
    log_path = tmp_path / "replay.json"
    log_path.write_text(
        json.dumps(
            {
                "schema": "cpm.replay.v1",
                "packet": "demo@1.0.0",
                "query": "auth",
                "indexer": "faiss-flatip",
                "reranker": "none",
                "selected_model": "model",
                "output_hash": "abc123",
            }
        ),
        encoding="utf-8",
    )

    def _fake_invoke(self, **kwargs):
        del self, kwargs
        return {"ok": True, "output_hash": "abc123", "results": []}

    monkeypatch.setattr(replay_mod.QueryCommand, "_invoke_retriever", _fake_invoke)
    code = cli_main(["replay", str(log_path)], start_dir=tmp_path)
    assert code == 0


def test_diff_command_reports_changes_and_threshold(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "docs.jsonl").write_text(
        json.dumps({"id": "a", "text": "alpha", "metadata": {"path": "a.md"}}) + "\n",
        encoding="utf-8",
    )
    (right / "docs.jsonl").write_text(
        json.dumps({"id": "a", "text": "alpha changed", "metadata": {"path": "a.md"}}) + "\n",
        encoding="utf-8",
    )
    np.array([1.0, 2.0], dtype=np.float16).tofile(left / "vectors.f16.bin")
    np.array([3.0, 4.0], dtype=np.float16).tofile(right / "vectors.f16.bin")

    code = cli_main(
        ["diff", str(left), str(right), "--max-drift", "0.01"],
        start_dir=tmp_path,
    )
    assert code == 1
