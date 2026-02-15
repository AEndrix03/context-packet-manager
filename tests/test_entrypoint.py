import importlib
from pathlib import Path

import pytest

from cpm_cli import __main__ as cli_entry
from cpm_core.registry import CPMRegistryEntry
from cpm_core.sources.models import LocalPacket, PacketReference


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


def test_dispatch_supports_builtin_embed_command(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    code = cli_main.main(["embed", "list"], start_dir=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "[cpm:embed]" in out


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


def test_query_command_supports_source_uri(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")
    source_dir = tmp_path / "source-packet"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "manifest.json").write_text("{}", encoding="utf-8")

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

    assert code == 0
    assert "source=dir://" in out
    packet_arg = str(captured.get("packet") or "")
    assert packet_arg
    assert Path(packet_arg).exists()
    assert str(Path(packet_arg).resolve()).startswith(str((tmp_path / ".cpm" / "cache" / "objects").resolve()))


def test_query_command_supports_registry_shortcut_and_embed_override(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")
    source_dir = tmp_path / "source-packet"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "manifest.json").write_text("{}", encoding="utf-8")

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
            "--workspace-dir",
            str(tmp_path),
            "--registry",
            f"dir://{source_dir}",
            "--query",
            "auth",
            "--embed",
            "mini-model",
        ],
        start_dir=tmp_path,
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "source=dir://" in out
    assert captured.get("selected_model") == "mini-model"


def test_query_command_supports_registry_base_with_packet(
    monkeypatch, tmp_path: Path
) -> None:
    cli_main = importlib.import_module("cpm_cli.main")
    query_builtin = importlib.import_module("cpm_core.builtins.query")
    resolved: dict[str, str] = {}
    cached_packet = tmp_path / ".cpm" / "cache" / "objects" / "fake"
    cached_packet.mkdir(parents=True, exist_ok=True)

    def _fake_resolve_and_fetch(self, uri: str):
        resolved["uri"] = uri
        return (
            PacketReference(uri=uri, resolved_uri=uri, digest="sha256:" + ("a" * 64)),
            LocalPacket(path=cached_packet, cache_key="fake", cached=False),
        )

    def _fake_retrieve(self, identifier: str, **kwargs):
        del self, identifier
        return {"ok": True, "packet": kwargs.get("packet"), "results": []}

    monkeypatch.setattr(query_builtin.SourceResolver, "resolve_and_fetch", _fake_resolve_and_fetch)
    monkeypatch.setattr(query_builtin.NativeFaissRetriever, "retrieve", _fake_retrieve)
    code = cli_main.main(
        [
            "query",
            "--workspace-dir",
            str(tmp_path),
            "--packet",
            "demo@1.0.0",
            "--registry",
            "registry.local/project",
            "--query",
            "auth",
        ],
        start_dir=tmp_path,
    )
    assert code == 0
    assert resolved["uri"] == "oci://registry.local/project/demo@1.0.0"
