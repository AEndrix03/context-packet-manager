from __future__ import annotations

import json
from pathlib import Path

import pytest

from cpm_cli.main import main as cli_main


def _prepare_packet(workspace_root: Path, *, name: str = "demo", version: str = "1.0.0", model: str = "model-lock") -> Path:
    packet_dir = workspace_root / "packages" / name / version
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / "cpm.yml").write_text(f"name: {name}\nversion: {version}\n", encoding="utf-8")
    (packet_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "packet_id": name,
                "embedding": {"provider": "x", "model": model, "dim": 2, "dtype": "float16", "normalized": True},
            }
        ),
        encoding="utf-8",
    )
    return packet_dir


def test_query_uses_selected_model_from_install_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))
    _prepare_packet(workspace_root)
    lock_path = workspace_root / "state" / "install" / "demo.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "selected_model": "model-lock",
                "suggested_retriever": "missing:retriever",
            }
        ),
        encoding="utf-8",
    )

    import cpm_core.builtins.query as query_mod

    captured: dict[str, object] = {}

    def _fake_retrieve(self, identifier: str, **kwargs):
        del self
        captured.update(kwargs)
        return {"ok": True, "query": identifier, "packet": kwargs.get("packet"), "results": []}

    monkeypatch.setattr(query_mod.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main(["query", "--packet", "demo", "--query", "hello"], start_dir=tmp_path)
    assert code == 0
    assert captured.get("selected_model") == "model-lock"


def test_query_auto_writes_install_lock_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))
    _prepare_packet(workspace_root, model="auto-model")

    import cpm_core.builtins.query as query_mod

    def _fake_retrieve(self, identifier: str, **kwargs):
        del self
        return {"ok": True, "query": identifier, "packet": kwargs.get("packet"), "results": []}

    monkeypatch.setattr(query_mod.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main(["query", "--packet", "demo", "--query", "hello"], start_dir=tmp_path)
    assert code == 0
    lock_path = workspace_root / "state" / "install" / "demo.lock.json"
    assert lock_path.exists()
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["selected_model"] == "auto-model"
