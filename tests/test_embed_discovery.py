from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

from cpm_builtin.embeddings import EmbeddingsConfigService


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _DiscoveryHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/v1/models":
            self.send_error(404)
            return
        payload = {"data": [{"id": "model-a"}]}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if self.path != "/v1/embeddings":
            self.send_error(404)
            return
        payload = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        del format, args
        return


def _start_server() -> tuple[_ThreadedServer, str]:
    server = _ThreadedServer(("127.0.0.1", 0), _DiscoveryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _stop_server(server: _ThreadedServer) -> None:
    server.shutdown()
    server.server_close()


def test_refresh_discovery_and_probe(tmp_path: Path) -> None:
    server, base_url = _start_server()
    try:
        config = f"""
default: local
providers:
  local:
    type: http
    url: {base_url}
    http:
      base_url: {base_url}
      embeddings_path: /v1/embeddings
      models_path: /v1/models
"""
        config_path = tmp_path / "embeddings.yml"
        config_path.write_text(config, encoding="utf-8")
        service = EmbeddingsConfigService(tmp_path)
        data = service.refresh_discovery(force=True)
        assert "local" in data
        assert data["local"]["models"] == ["model-a"]
        assert data["local"]["dims"]["model-a"] == 3
        cached = service.read_discovery()
        assert "local" in cached
    finally:
        _stop_server(server)
