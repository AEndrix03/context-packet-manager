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
    l2_normalize,
)


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _MockEmbedHandler(BaseHTTPRequestHandler):
    server_version = "MockEmbed/1.0"
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        expected_path = getattr(self.server, "expected_path", "/v1/embeddings")
        if self.path != expected_path:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        body = json.loads(payload.decode("utf-8"))
        self.server.last_path = self.path
        self.server.last_headers = {str(k): str(v) for k, v in self.headers.items()}
        texts = body.get("texts") or []
        response_vectors = getattr(self.server, "response_vectors", None)
        if response_vectors is None:
            dims = getattr(self.server, "response_dim", 0) or 0
            vectors = [[float(idx) for _ in range(dims)] for idx, _ in enumerate(texts)]
        else:
            vectors = [list(row) for row in response_vectors]
        response = json.dumps({"vectors": vectors}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return


def _start_mock_server(
    response_dim: int,
    *,
    expected_path: str = "/v1/embeddings",
    response_vectors: list[list[float]] | None = None,
) -> tuple[_ThreadedServer, str]:
    server = _ThreadedServer(("127.0.0.1", 0), _MockEmbedHandler)
    server.response_dim = response_dim
    server.response_vectors = response_vectors
    server.expected_path = expected_path
    server.last_path = None
    server.last_headers = {}
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
    http:
      base_url: http://example.local
      path: /v1/embeddings
      timeout: 2
      headers_static:
        Authorization: Bearer secret
    batch_size: 4
    hints:
      model: test-model
      dim: 3
      normalize: true
      task: retrieval.query
    extra:
      tag: ping
    normalize_mode: client
"""
    path = tmp_path / "embeddings.yml"
    path.write_text(config, encoding="utf-8")

    service = EmbeddingsConfigService(tmp_path)
    providers = service.list_providers()
    assert providers and providers[0].name == "remote"
    default = service.default_provider()
    assert default is not None and default.name == "remote"
    assert default.resolved_http_base_url == "http://example.local"
    assert default.resolved_http_path == "/v1/embeddings"
    assert default.resolved_http_timeout == 2.0
    assert default.resolved_headers_static == {"Authorization": "Bearer secret"}
    assert default.resolved_hint_model == "test-model"
    assert default.resolved_hint_dim == 3
    assert default.hint_normalize is True
    assert default.normalize_mode == "client"
    assert default.hint_task == "retrieval.query"
    assert default.extra["tag"] == "ping"


def test_http_connector_batches_and_cache(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(response_dim=4)
    try:
        provider = EmbeddingProviderConfig(
            name="mock",
            type="http",
            url=endpoint,
            batch_size=2,
            http_timeout=1.5,
            http_headers_static={"Authorization": "Bearer static"},
            hint_model="model",
            hint_dim=4,
            hint_normalize=True,
            hint_task="retrieval.query",
        )
        connector = HttpEmbeddingConnector(provider)
        texts = ["a", "b", "c"]
        matrix = connector.embed_texts(texts)
        assert isinstance(matrix, np.ndarray)
        assert matrix.shape == (3, 4)
        assert matrix.dtype == np.float32
        assert server.last_path == "/v1/embeddings"
        assert server.last_headers["Authorization"] == "Bearer static"
        assert server.last_headers["X-Embedding-Dim"] == "4"
        assert server.last_headers["X-Embedding-Normalize"] == "true"
        assert server.last_headers["X-Embedding-Task"] == "retrieval.query"
        assert server.last_headers["X-Model-Hint"] == "model"

        cache_dir = tmp_path / "cache"
        cache = EmbeddingCache(cache_root=cache_dir)
        cache.set(provider.name, "a", matrix[0])
        cached = cache.get(provider.name, "a")
        assert cached == pytest.approx([float(x) for x in matrix[0]])
    finally:
        _shutdown(server)


def test_http_connector_accepts_full_embeddings_endpoint_url(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(response_dim=2)
    try:
        provider = EmbeddingProviderConfig(
            name="full-endpoint",
            type="http",
            url=f"{endpoint}/v1/embeddings",
            batch_size=1,
            hint_dim=2,
        )
        connector = HttpEmbeddingConnector(provider)
        matrix = connector.embed_texts(["a"])
        assert matrix.shape == (1, 2)
        assert connector.endpoint == f"{endpoint}/v1/embeddings"
        assert server.last_path == "/v1/embeddings"
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


def test_http_connector_normalizes_client_side_when_configured(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(response_dim=2)
    try:
        provider = EmbeddingProviderConfig(
            name="normalize-client",
            type="http",
            url=endpoint,
            batch_size=2,
            hint_dim=2,
            hint_normalize=True,
            normalize_mode="client",
        )
        connector = HttpEmbeddingConnector(provider)
        matrix = connector.embed_texts(["a", "b"])
        assert matrix[1].tolist() == pytest.approx([0.70710677, 0.70710677], rel=1e-6)
    finally:
        _shutdown(server)


def test_http_connector_rejects_non_finite_values(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(
        response_dim=2,
        response_vectors=[[0.0, 1.0], [float("nan"), 2.0]],
    )
    try:
        provider = EmbeddingProviderConfig(
            name="bad-values",
            type="http",
            url=endpoint,
            hint_dim=2,
        )
        connector = HttpEmbeddingConnector(provider)
        with pytest.raises(ValueError, match="NaN or Inf"):
            connector.embed_texts(["a", "b"])
    finally:
        _shutdown(server)


def test_http_connector_auto_normalizes_when_needed(tmp_path: Path) -> None:
    server, endpoint = _start_mock_server(
        response_dim=2,
        response_vectors=[[1.0, 0.0], [3.0, 4.0]],
    )
    try:
        provider = EmbeddingProviderConfig(
            name="auto-normalize",
            type="http",
            url=endpoint,
            hint_dim=2,
            hint_normalize=True,
            normalize_mode="auto",
        )
        connector = HttpEmbeddingConnector(provider)
        matrix = connector.embed_texts(["a", "b"])
        assert matrix[0].tolist() == pytest.approx([1.0, 0.0], rel=1e-6)
        assert matrix[1].tolist() == pytest.approx([0.6, 0.8], rel=1e-6)
    finally:
        _shutdown(server)


def test_l2_normalize_preserves_zero_rows() -> None:
    matrix = np.asarray([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    normalized = l2_normalize(matrix)
    assert normalized[0].tolist() == pytest.approx([0.6, 0.8], rel=1e-6)
    assert normalized[1].tolist() == [0.0, 0.0]
