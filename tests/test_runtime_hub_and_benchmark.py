from __future__ import annotations

from pathlib import Path

import pytest

import cpm_core.builtins.benchmark as benchmark_mod
import cpm_core.builtins.query as query_mod
from cpm_cli.main import main as cli_main
from cpm_core.registry.entry import CPMRegistryEntry


def test_query_denies_when_hub_policy_denies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))
    config_path = workspace_root / "config" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "[hub]",
                'url = "http://hub.local"',
                "enforce_remote_policy = true",
            ]
        ),
        encoding="utf-8",
    )
    source_dir = tmp_path / "source-packet"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        query_mod.HubClient,
        "evaluate_policy",
        lambda self, context, policy: {"allow": False, "decision": "deny", "reason": "hub_blocked"},
    )
    code = cli_main(
        [
            "query",
            "--workspace-dir",
            str(tmp_path),
            "--source",
            f"dir://{source_dir}",
            "--query",
            "auth",
        ],
        start_dir=tmp_path,
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "hub policy deny" in out


def test_benchmark_command_outputs_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))

    class _FakeRetriever:
        def retrieve(self, identifier: str, **kwargs):
            del identifier, kwargs
            return {
                "ok": True,
                "packet": "demo",
                "query": "auth",
                "k": 5,
                "results": [{"id": "a", "score": 0.9, "text": "alpha", "metadata": {"path": "docs/a.md"}}],
                "compiled_context": {
                    "token_estimate": 120,
                    "core_snippets": [{"citation": "docs/a.md"}],
                },
            }

    entry = CPMRegistryEntry(
        group="cpm",
        name="native-retriever",
        target=_FakeRetriever,
        kind="retriever",
        origin="builtin",
    )
    monkeypatch.setattr(benchmark_mod.QueryCommand, "_load_retriever_entries", lambda self, root: [entry])
    monkeypatch.setattr(benchmark_mod.QueryCommand, "_resolve_retriever_entry", lambda self, entries, requested: entry)
    code = cli_main(
        [
            "benchmark",
            "--workspace-dir",
            str(tmp_path),
            "--packet",
            "demo",
            "--query",
            "auth",
            "--runs",
            "2",
            "--format",
            "json",
        ],
        start_dir=tmp_path,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert '"runs": 2' in out
    assert '"citation_coverage_avg"' in out
