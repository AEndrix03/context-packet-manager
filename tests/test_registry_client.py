"""Integration tests for registry commands using a mock HTTP registry."""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, message="'cgi' is deprecated and slated for removal in Python 3.13.*")
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*filter extracted tar archives.*",
)

import cgi
import hashlib
import http.server
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

from cli.commands.install import cmd_cpm_install
from cli.commands.list_remote import cmd_cpm_list_remote
from cli.commands.publish import cmd_cpm_publish
from cli.commands.update import cmd_cpm_update
from cli.core.cpm_pkg import (
    REQUIRED_ARTIFACTS,
    get_pinned_version,
    make_versioned_tar_from_build_dir,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Python 3.14 will, by default, filter extracted tar archives and reject files or modify their metadata.*"
)


class MockRegistryState:
    """In-memory registry state that mirrors the real API payloads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.packages: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def publish(self, name: str, version: str, data: bytes, *, overwrite: bool) -> Dict[str, Any]:
        key = (name, version)
        with self._lock:
            if key in self.packages and not overwrite:
                raise ValueError("already exists")
            metadata = self._build_metadata(name, version, data)
            self.packages[key] = metadata
            return metadata

    def _build_metadata(self, name: str, version: str, data: bytes) -> Dict[str, Any]:
        sha256 = hashlib.sha256(data).hexdigest()
        return {
            "name": name,
            "version": version,
            "sha256": sha256,
            "size_bytes": len(data),
            "object_key": f"blobs/sha256/{sha256}.tar.gz",
            "checksum": sha256,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "yanked": False,
            "data": data,
        }

    def get_version(self, name: str, version: str) -> Dict[str, Any] | None:
        return self.packages.get((name, version))

    def version_payload(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        payload = metadata.copy()
        payload.pop("data", None)
        return payload

    def list_versions(self, name: str, *, include_yanked: bool) -> list[Dict[str, Any]]:
        with self._lock:
            result: list[Dict[str, Any]] = []
            for (pkg_name, pkg_version), meta in sorted(self.packages.items()):
                if pkg_name != name:
                    continue
                if not include_yanked and meta.get("yanked"):
                    continue
                result.append(self.version_payload(meta))
            return result


class _MockRegistryRequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _write_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_bytes(self, status: int, data: bytes, extra_headers: Dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _state(self) -> MockRegistryState:
        return self.server.state  # type: ignore[attr-defined]

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if parts[:2] == ["v1", "packages"] and len(parts) == 4:
            name, version = parts[2], parts[3]
            if self._state().get_version(name, version):
                self.send_response(200)
            else:
                self.send_response(404)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if parts[:2] != ["v1", "packages"]:
            self.send_response(404)
            self.end_headers()
            return

        if len(parts) == 3:
            name = parts[2]
            include_yanked = parse_qs(parsed.query).get("include_yanked", ["false"])[0].lower() in (
                "1",
                "true",
                "yes",
            )
            versions = self._state().list_versions(name, include_yanked=include_yanked)
            self._write_json(200, {"name": name, "versions": versions})
            return

        if len(parts) == 4:
            name, version = parts[2], parts[3]
            metadata = self._state().get_version(name, version)
            if not metadata:
                self.send_response(404)
                self.end_headers()
                return
            self._write_json(200, self._state().version_payload(metadata))
            return

        if len(parts) == 5 and parts[4] == "download":
            name, version = parts[2], parts[3]
            metadata = self._state().get_version(name, version)
            if not metadata:
                self.send_response(404)
                self.end_headers()
                return
            headers = {"Content-Disposition": f'attachment; filename="{name}-{version}.tar.gz"'}
            self._write_bytes(200, metadata["data"], extra_headers=headers)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if parts[:2] != ["v1", "packages"] or len(parts) != 4:
            self.send_response(404)
            self.end_headers()
            return

        name, version = parts[2], parts[3]
        query = parse_qs(parsed.query)
        overwrite = query.get("overwrite", ["false"])[0].lower() in ("1", "true", "yes")
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        fs = cgi.FieldStorage(fp=self.rfile, environ=env, keep_blank_values=True)
        if "file" not in fs:
            self._write_json(400, {"detail": "missing file upload"})
            return
        file_field = fs["file"]
        data = file_field.file.read()
        if not data:
            self._write_json(400, {"detail": "empty upload"})
            return

        try:
            meta = self._state().publish(name, version, data, overwrite=overwrite)
        except ValueError:
            self._write_json(409, {"detail": "already exists"})
            return

        response = {
            "ok": True,
            "name": meta["name"],
            "version": meta["version"],
            "sha256": meta["sha256"],
            "object_key": meta["object_key"],
            "size_bytes": meta["size_bytes"],
        }
        self._write_json(201, response)

    def log_message(self, *_: Any) -> None:  # pragma: no cover - avoid noisy logs
        return


class _ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


class MockRegistryServer:
    """Helper that runs the mock registry in a background thread."""

    def __init__(self) -> None:
        self.state = MockRegistryState()
        self.httpd = _ThreadingHTTPServer(("127.0.0.1", 0), _MockRegistryRequestHandler)
        self.httpd.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.url = ""

    def start(self) -> None:
        self.thread.start()
        host, port = self.httpd.server_address
        self.url = f"http://{host}:{port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def publish(self, name: str, version: str, data: bytes, *, overwrite: bool = False) -> Dict[str, Any]:
        return self.state.publish(name, version, data, overwrite=overwrite)


def _prepare_packet_dir(base: Path, name: str, version: str) -> Path:
    src = base / f"{name}-{version}"
    src.mkdir(parents=True, exist_ok=True)
    for artifact in REQUIRED_ARTIFACTS:
        target = src / artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        if artifact.endswith(".bin"):
            target.write_bytes(b"\x00")
        elif artifact.endswith(".jsonl"):
            target.write_text("[]", encoding="utf-8")
        else:
            target.write_text("{}", encoding="utf-8")
    target = src / "cpm.yml"
    target.write_text(f"name: {name}\nversion: {version}\n", encoding="utf-8")
    return src


def _make_tar_bytes(tmp_dir: Path, name: str, version: str) -> bytes:
    build_dir = _prepare_packet_dir(tmp_dir / f"build-{version}", name, version)
    tar_path = tmp_dir / f"{name}-{version}.tar.gz"
    make_versioned_tar_from_build_dir(build_dir, name, version, tar_path)
    return tar_path.read_bytes()


def test_registry_commands_install_update_and_list(tmp_path: Path, capfd: Any) -> None:
    server = MockRegistryServer()
    server.start()
    try:
        name = "demo"
        version_v1 = "0.1.0"
        version_v2 = "0.2.0"
        server.publish(name, version_v1, _make_tar_bytes(tmp_path, name, version_v1), overwrite=True)

        list_args = SimpleNamespace(
            name=name,
            registry=server.url,
            include_yanked=False,
            format="text",
            sort_semantic=False,
        )
        cmd_cpm_list_remote(list_args)
        captured = capfd.readouterr()
        assert f"{name}@{version_v1}" in captured.out

        cpm_dir = tmp_path / ".cpm"
        install_args = SimpleNamespace(spec=f"{name}@{version_v1}", registry=server.url, cpm_dir=str(cpm_dir))
        cmd_cpm_install(install_args)
        assert (cpm_dir / name / "cpm.yml").exists()

        server.publish(name, version_v2, _make_tar_bytes(tmp_path, name, version_v2))
        update_args = SimpleNamespace(spec=name, registry=server.url, cpm_dir=str(cpm_dir), purge=False)
        cmd_cpm_update(update_args)
        pinned = get_pinned_version(cpm_dir, name)
        assert pinned == version_v2
    finally:
        server.stop()


def test_registry_publish_roundtrip(tmp_path: Path, capfd: Any) -> None:
    server = MockRegistryServer()
    server.start()
    try:
        name = "publish-me"
        version = "1.0.0"
        src_dir = _prepare_packet_dir(tmp_path / "publish-src", name, version)
        args = SimpleNamespace(from_dir=str(src_dir), registry=server.url, overwrite=False, yes=True)
        cmd_cpm_publish(args)
        captured = capfd.readouterr()
        assert "ok publish-me@1.0.0" in captured.out
        metadata = server.state.get_version(name, version)
        assert metadata is not None
        assert metadata["sha256"] in captured.out
    finally:
        server.stop()
