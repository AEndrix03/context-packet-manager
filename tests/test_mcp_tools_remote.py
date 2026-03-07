from __future__ import annotations

import json
import sys
from pathlib import Path

from cpm_core.sources.models import LocalPacket, PacketReference

sys.path.insert(0, str((Path(__file__).resolve().parents[1] / "cpm_plugins" / "mcp").resolve()))
from cpm_mcp_plugin import remote  # type: ignore  # noqa: E402
from cpm_mcp_plugin.server import run_server  # type: ignore  # noqa: E402


def _write_min_packet(root: Path) -> None:
    (root / "faiss").mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "cpm": {"name": "demo", "version": "1.0.0"},
                "embedding": {"model": "test-model", "max_seq_length": 1024},
            }
        ),
        encoding="utf-8",
    )
    (root / "docs.jsonl").write_text(
        json.dumps({"id": "doc-1", "text": "auth setup", "metadata": {"path": "README.md", "line_start": 10}})
        + "\n",
        encoding="utf-8",
    )
    (root / "faiss" / "index.faiss").write_text("stub", encoding="utf-8")


def test_lookup_remote_uses_registry_env_and_alias_cache(monkeypatch, tmp_path: Path) -> None:
    cpm_root = tmp_path / ".cpm"
    monkeypatch.setenv("CPM_ROOT", str(cpm_root))
    monkeypatch.setenv("REGISTRY", "registry.local/project")

    calls = {"lookup": 0}

    class _FakeResolver:
        def __init__(self, workspace_root: Path):
            self.workspace_root = workspace_root

        def lookup_metadata(self, uri: str):
            calls["lookup"] += 1
            assert uri == "oci://registry.local/project/demo:latest"
            reference = PacketReference(
                uri=uri,
                resolved_uri=uri,
                digest="sha256:" + ("a" * 64),
                metadata={"ref": "registry.local/project/demo:latest", "metadata_digest": "sha256:" + ("b" * 64)},
            )
            metadata = {
                "packet": {
                    "name": "demo",
                    "version": "1.0.0",
                    "entrypoints": ["query"],
                    "kind": "knowledge",
                    "capabilities": ["rag"],
                },
                "compat": {"os": ["linux"], "arch": ["amd64"]},
            }
            return reference, metadata

    monkeypatch.setattr(remote, "SourceResolver", _FakeResolver)
    first = remote.lookup_remote(name="demo", entrypoint="query", capability="rag")
    second = remote.lookup_remote(name="demo", entrypoint="query", capability="rag")

    assert first["ok"] is True
    assert first["selected"]["pinned_uri"] == "oci://registry.local/project/demo@sha256:" + ("a" * 64)
    assert second["ok"] is True
    assert calls["lookup"] == 1


def test_lookup_remote_falls_back_from_localhost_to_host_docker_internal(monkeypatch, tmp_path: Path) -> None:
    cpm_root = tmp_path / ".cpm"
    monkeypatch.setenv("CPM_ROOT", str(cpm_root))
    monkeypatch.setenv("REGISTRY", "localhost:5000")
    calls: list[str] = []

    class _FakeResolver:
        def __init__(self, workspace_root: Path):
            self.workspace_root = workspace_root

        def lookup_metadata(self, uri: str):
            calls.append(uri)
            if "localhost:5000" in uri:
                raise TimeoutError("oras command timed out after 10.0s")
            reference = PacketReference(
                uri=uri,
                resolved_uri=uri,
                digest="sha256:" + ("c" * 64),
                metadata={
                    "ref": "host.docker.internal:5000/demo:latest",
                    "metadata_digest": "sha256:" + ("d" * 64),
                },
            )
            metadata = {"packet": {"name": "demo", "version": "1.0.0", "entrypoints": ["query"]}}
            return reference, metadata

    monkeypatch.setattr(remote, "SourceResolver", _FakeResolver)
    payload = remote.lookup_remote(name="demo", alias="latest")

    assert payload["ok"] is True
    assert payload["resolved_source_uri"] == "oci://host.docker.internal:5000/demo:latest"
    assert calls == [
        "oci://localhost:5000/demo:latest",
        "oci://host.docker.internal:5000/demo:latest",
    ]


def test_lookup_remote_writes_failure_log_and_hint(monkeypatch, tmp_path: Path) -> None:
    cpm_root = tmp_path / ".cpm"
    monkeypatch.setenv("CPM_ROOT", str(cpm_root))
    monkeypatch.setenv("REGISTRY", "localhost:5000")

    class _FakeResolver:
        def __init__(self, workspace_root: Path):
            self.workspace_root = workspace_root

        def lookup_metadata(self, uri: str):
            raise TimeoutError("oras command timed out after 10.0s")

    monkeypatch.setattr(remote, "SourceResolver", _FakeResolver)
    payload = remote.lookup_remote(name="demo", version="1.0.0")

    assert payload["ok"] is False
    assert payload["error"] == "lookup_failed"
    assert "host.docker.internal" in str(payload["detail"])
    log_path = cpm_root / "logs" / "mcp-lookup.log"
    assert log_path.exists()
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any('"event": "lookup_failed"' in line for line in lines)


def test_query_remote_cache_hit_skips_remote_fetch(monkeypatch, tmp_path: Path) -> None:
    cpm_root = tmp_path / ".cpm"
    digest = "sha256:" + ("1" * 64)
    safe_digest = remote._safe_key(digest)
    monkeypatch.setenv("CPM_ROOT", str(cpm_root))
    monkeypatch.setenv("EMBEDDING_URL", "http://embed.local")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-model")

    payload_dir = cpm_root / "cas" / safe_digest / "payload"
    _write_min_packet(payload_dir)
    fingerprint = remote._embedding_fingerprint(remote.load_settings(cpm_root=str(cpm_root)))
    index_dir = cpm_root / "index" / safe_digest / fingerprint
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "index.faiss").write_text("stub", encoding="utf-8")

    class _ResolverShouldNotRun:
        def __init__(self, workspace_root: Path):
            self.workspace_root = workspace_root

        def resolve_and_fetch(self, uri: str):
            raise AssertionError("resolve_and_fetch should not run on cache hit")

    class _FakeRetriever:
        def retrieve(self, identifier: str, **kwargs):
            return {
                "ok": True,
                "results": [{"score": 0.9, "id": "doc-1", "text": "auth setup details", "metadata": {"path": "README.md"}}],
            }

    monkeypatch.setattr(remote, "SourceResolver", _ResolverShouldNotRun)
    monkeypatch.setattr(remote, "_build_native_retriever", lambda: _FakeRetriever())

    payload = remote.query_remote(ref=f"oci://registry.local/project/demo@{digest}", q="auth setup", k=3)
    assert payload["ok"] is True
    assert payload["cache"]["hit"] is True
    assert payload["digest"] == digest
    assert len(payload["results"]) == 1


def test_query_remote_cache_miss_materializes_and_caches(monkeypatch, tmp_path: Path) -> None:
    cpm_root = tmp_path / ".cpm"
    source_payload = tmp_path / "payload-src"
    _write_min_packet(source_payload)
    monkeypatch.setenv("CPM_ROOT", str(cpm_root))
    monkeypatch.setenv("EMBEDDING_URL", "http://embed.local")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-model")

    calls = {"resolve": 0}
    digest = "sha256:" + ("2" * 64)

    class _FakeResolver:
        def __init__(self, workspace_root: Path):
            self.workspace_root = workspace_root

        def resolve_and_fetch(self, uri: str):
            calls["resolve"] += 1
            reference = PacketReference(
                uri=uri,
                resolved_uri=uri,
                digest=digest,
                metadata={"ref": "registry.local/project/demo:latest"},
            )
            packet = LocalPacket(path=source_payload, cache_key="cache-key", cached=False)
            return reference, packet

    class _FakeRetriever:
        def retrieve(self, identifier: str, **kwargs):
            return {
                "ok": True,
                "results": [{"score": 0.8, "id": "doc-1", "text": "auth setup details", "metadata": {"path": "README.md"}}],
            }

    monkeypatch.setattr(remote, "SourceResolver", _FakeResolver)
    monkeypatch.setattr(remote, "_build_native_retriever", lambda: _FakeRetriever())

    payload = remote.query_remote(ref="oci://registry.local/project/demo:latest", q="auth setup", k=3)
    assert payload["ok"] is True
    assert payload["cache"]["hit"] is False
    assert calls["resolve"] == 1

    safe_digest = remote._safe_key(digest)
    fingerprint = remote._embedding_fingerprint(remote.load_settings(cpm_root=str(cpm_root)))
    assert (cpm_root / "cas" / safe_digest / "payload" / "manifest.json").exists()
    assert (cpm_root / "index" / safe_digest / fingerprint / "index.faiss").exists()


def test_plan_and_evidence_tools_are_deterministic(monkeypatch) -> None:
    def _fake_lookup_remote(**kwargs):
        return {
            "ok": True,
            "candidates": [
                {
                    "pinned_uri": "oci://registry.local/project/demo@sha256:" + ("3" * 64),
                    "name": "demo",
                    "version": "1.0.0",
                    "entrypoints": ["query"],
                    "kind": "knowledge",
                    "capabilities": ["rag", "search"],
                }
            ],
        }

    def _fake_query_remote(**kwargs):
        return {
            "ok": True,
            "digest": "sha256:" + ("3" * 64),
            "pinned_uri": "oci://registry.local/project/demo@sha256:" + ("3" * 64),
            "results": [
                {"score": 0.9, "path": "README.md", "snippet": "alpha"},
                {"score": 0.8, "path": "README.md", "snippet": "alpha"},
                {"score": 0.7, "path": "docs.md", "snippet": "beta"},
            ],
        }

    monkeypatch.setattr(remote, "lookup_remote", _fake_lookup_remote)
    monkeypatch.setattr(remote, "query_remote", _fake_query_remote)

    plan = remote.plan_from_intent(intent="Need packet:demo for search", constraints={"entrypoint": "query"})
    digest = remote.evidence_digest(ref="oci://registry.local/project/demo:latest", question="auth")
    assert plan["ok"] is True
    assert len(plan["selected"]) == 1
    assert digest["ok"] is True
    assert len(digest["evidence"]) == 2


def test_plan_from_intent_prefers_lookup_for_metadata_intent(monkeypatch) -> None:
    def _fake_lookup_remote(**kwargs):
        return {
            "ok": True,
            "candidates": [
                {
                    "pinned_uri": "oci://registry.local/project/demo@sha256:" + ("4" * 64),
                    "name": "demo",
                    "version": "1.2.3",
                    "entrypoints": ["query"],
                    "kind": "knowledge",
                    "capabilities": ["rag", "search"],
                }
            ],
        }

    def _query_should_not_run(**kwargs):
        raise AssertionError("query_remote should not run for lookup-oriented planning")

    monkeypatch.setattr(remote, "lookup_remote", _fake_lookup_remote)
    monkeypatch.setattr(remote, "query_remote", _query_should_not_run)

    plan = remote.plan_from_intent(
        intent="lookup metadata for packet:demo latest version and capabilities",
        constraints={"alias": "latest"},
    )

    assert plan["ok"] is True
    assert plan["intent_mode"] == "lookup"
    assert len(plan["selected"]) == 1
    assert plan["selected"][0]["entrypoint"] == "lookup"
    assert plan["selected"][0]["args_template"]["ref"].startswith("oci://registry.local/project/demo@sha256:")


def test_run_server_applies_env_overrides(monkeypatch) -> None:
    run_log = []

    from cpm_mcp_plugin import server

    monkeypatch.setattr(server.mcp, "run", lambda: run_log.append("ran"))
    run_server(
        cpm_root=".cpm-test",
        registry="registry.local/project",
        embedding_url="http://embed.local",
        embedding_model="model-x",
    )
    assert run_log == ["ran"]
