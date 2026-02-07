import importlib
from pathlib import Path

from cpm_cli import __main__ as cli_entry
import pytest
from cpm_core.registry import CPMRegistryEntry


def test_console_module_entrypoint_delegates_to_cli_main(monkeypatch):
    cli_main = importlib.import_module("cpm_cli.main")
    monkeypatch.setattr(cli_main, "main", lambda: 7)

    assert cli_entry.run() == 7
    assert cli_entry.main() == 7


def test_dispatch_supports_lookup_command(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    code = cli_main.main(["lookup"], start_dir=tmp_path)

    assert code == 0
    assert "[cpm:lookup]" in capsys.readouterr().out


def test_dispatch_rejects_removed_legacy_alias(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    code = cli_main.main(["embed:status"], start_dir=tmp_path)

    assert code == 1
    assert "embed:status" in capsys.readouterr().out


def test_query_command_dispatches_to_native_retriever(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")

    def _fake_retrieve(self, identifier: str, **kwargs):
        return {
            "ok": True,
            "packet": kwargs.get("packet"),
            "query": identifier,
            "k": kwargs.get("k", 5),
            "results": [
                {
                    "score": 0.91,
                    "id": "doc-1",
                    "text": "Authentication setup guide",
                    "metadata": {"path": "docs/auth.md"},
                }
            ],
        }

    monkeypatch.setattr(query_builtin.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main.main(
        ["query", "--packet", "my-docs", "--query", "authentication setup", "-k", "5"],
        start_dir=tmp_path,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "[cpm:query] retriever=cpm:native-retriever packet=my-docs k=5" in out
    assert "Authentication setup guide" in out


def test_query_command_uses_default_embedding_provider(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")
    add_code = cli_main.main(
        [
            "embed",
            "add",
            "--name",
            "local",
            "--url",
            "http://localhost:8000/v1/embeddings",
            "--set-default",
        ],
        start_dir=tmp_path,
    )
    assert add_code == 0

    captured: dict[str, object] = {}

    def _fake_retrieve(self, identifier: str, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "packet": kwargs.get("packet"),
            "query": identifier,
            "k": kwargs.get("k", 5),
            "results": [],
        }

    monkeypatch.setattr(query_builtin.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main.main(
        ["query", "--packet", "my-docs", "--query", "authentication setup", "-k", "5"],
        start_dir=tmp_path,
    )

    assert code == 0
    assert captured.get("embed_url") == "http://localhost:8000/v1/embeddings"
    assert captured.get("embed_mode") == "http"
    assert "[cpm:query] retriever=cpm:native-retriever packet=my-docs k=5" in capsys.readouterr().out


def test_query_command_supports_custom_retriever_selection(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")

    class _CustomRetriever:
        def retrieve(self, identifier: str, **kwargs):
            return {
                "ok": True,
                "packet": kwargs.get("packet"),
                "query": identifier,
                "k": kwargs.get("k", 5),
                "results": [{"score": 0.5, "id": "x", "text": "custom", "metadata": {}}],
            }

    custom_entry = CPMRegistryEntry(
        group="sample",
        name="custom-retriever",
        target=_CustomRetriever,
        kind="retriever",
        origin="test",
    )
    native_entry = CPMRegistryEntry(
        group="cpm",
        name="native-retriever",
        target=query_builtin.NativeFaissRetriever,
        kind="retriever",
        origin="builtin",
    )

    monkeypatch.setattr(
        query_builtin.QueryCommand,
        "_load_retriever_entries",
        lambda self, workspace_root: [native_entry, custom_entry],
    )

    code = cli_main.main(
        [
            "query",
            "--packet",
            "my-docs",
            "--query",
            "auth",
            "--retriever",
            "custom-retriever",
        ],
        start_dir=tmp_path,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "[cpm:query] retriever=sample:custom-retriever packet=my-docs k=5" in out


def test_query_command_passes_indexer_and_reranker(
    monkeypatch, tmp_path: Path
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")
    captured: dict[str, object] = {}

    def _fake_retrieve(self, identifier: str, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "packet": kwargs.get("packet"),
            "query": identifier,
            "k": kwargs.get("k", 5),
            "results": [],
        }

    monkeypatch.setattr(query_builtin.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main.main(
        [
            "query",
            "--packet",
            "my-docs",
            "--query",
            "auth",
            "--indexer",
            "faiss-flatip",
            "--reranker",
            "token-diversity",
        ],
        start_dir=tmp_path,
    )

    assert code == 0
    assert captured.get("indexer") == "faiss-flatip"
    assert captured.get("reranker") == "token-diversity"
