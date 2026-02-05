import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

import numpy as np
import pytest

from cpm_builtin.embeddings import (
    EmbeddingCache,
    EmbeddingProviderConfig,
    EmbeddingsConfigService,
    HttpEmbeddingConnector,
)


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _MockEmbedHandler(BaseHTTPRequestHandler):
    server_version = "MockEmbed/1.0"
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        if self.path != "/embed":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        body = json.loads(payload.decode("utf-8"))
        texts = body.get("texts") or []
        dims = getattr(self.server, "response_dim", 0) or 0
        vectors = [[float(idx) for _ in range(dims)] for idx, _ in enumerate(texts)]
        response = json.dumps({"vectors": vectors}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return


def _start_mock_server(response_dim: int) -> tuple[_ThreadedServer, str]:
    server = _ThreadedServer(("127.0.0.1", 0), _MockEmbedHandler)
    server.response_dim = response_dim
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _shutdown(server: _ThreadedServer) -> None:
    server.shutdown()
    server.server_close()


def test_embeddings_config_parsing(tmp_path: Path) -> None:
    config = """
default: remote
providers:
  remote:
    type: http
    url: http://example.local
    timeout: 2
    batch_size: 4
    model: test-model
    dims: 3
    headers:
      Authorization: Bearer secret
    extra:
      tag: ping
"""
    path = tmp_path / "embeddings.yml"
    path.write_text(config, encoding="utf-8")

    service = EmbeddingsConfigService(tmp_path)
    providers = service.list_providers()
    assert providers and providers[0].name == "remote"
    default = service.default_provider()
    assert default is not None and default.name == "remote"
    assert default.headers == {"Authorization": "Bearer secret"}
    assert default.extra["tag"] == "ping"


def test_http_connector_batches_and_cache(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(response_dim=4)
    try:
        provider = EmbeddingProviderConfig(
            name="mock",
            type="http",
            url=endpoint,
            timeout=1.5,
            batch_size=2,
            model="model",
            dims=4,
        )
        connector = HttpEmbeddingConnector(provider)
        texts = ["a", "b", "c"]
        matrix = connector.embed_texts(texts)
        assert isinstance(matrix, np.ndarray)
        assert matrix.shape == (3, 4)
        assert matrix.dtype == np.float32

        cache_dir = tmp_path / "cache"
        cache = EmbeddingCache(cache_root=cache_dir)
        cache.set(provider.name, "a", matrix[0])
        cached = cache.get(provider.name, "a")
        assert cached == pytest.approx([float(x) for x in matrix[0]])
    finally:
        _shutdown(server)


def test_http_connector_validates_dims(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(response_dim=2)
    try:
        provider = EmbeddingProviderConfig(
            name="mismatch",
            type="http",
            url=endpoint,
            batch_size=1,
            dims=3,
        )
        connector = HttpEmbeddingConnector(provider)
        with pytest.raises(ValueError):
            connector.embed_texts(["only"])
    finally:
        _shutdown(server)
