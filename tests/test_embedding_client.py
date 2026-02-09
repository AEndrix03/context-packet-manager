from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any

import numpy as np
import pytest

from cpm_builtin.embeddings.client import EmbeddingClient


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _EmbeddingHandler(BaseHTTPRequestHandler):
    server_version = "MockEmbedding/1.0"
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:
        if self.path == "/v1/embeddings":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"ok": True})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/v1/embeddings":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            inputs = payload.get("input") or []
            data: list[dict[str, Any]] = []
            for idx, _text in enumerate(inputs):
                data.append({"index": idx, "embedding": [float(idx + 1), 0.0]})
            self._respond(200, {"object": "list", "data": data, "model": "mock-openai"})
            return

        if self.path == "/embed":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            texts = payload.get("texts") or []
            vectors = [[float(idx), float(idx)] for idx, _ in enumerate(texts)]
            self._respond(200, {"vectors": vectors})
            return

        self.send_error(404)

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def _start_server() -> tuple[_ThreadedServer, str]:
    server = _ThreadedServer(("127.0.0.1", 0), _EmbeddingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _stop_server(server: _ThreadedServer) -> None:
    server.shutdown()
    server.server_close()


def test_embedding_client_http_mode_uses_openai_endpoint() -> None:
    server, base_url = _start_server()
    try:
        client = EmbeddingClient(base_url=base_url, mode="http", timeout_s=1.0)
        assert client.health() is True
        vectors = client.embed_texts(
            ["a", "b"],
            model_name="test-model",
            max_seq_length=128,
            normalize=False,
            dtype="float32",
            show_progress=False,
        )
        assert isinstance(vectors, np.ndarray)
        assert vectors.shape == (2, 2)
        assert vectors.dtype == np.float32
    finally:
        _stop_server(server)


def test_embedding_client_auto_batches_on_too_many_items(monkeypatch) -> None:
    calls: list[int] = []

    def fake_embed_texts(self, texts, *, model=None, hints=None, extra=None, normalize=False):
        del self, model, hints, extra, normalize
        size = len(list(texts))
        calls.append(size)
        if size > 2:
            raise ValueError(
                "bad request (status=400) payload_snippet='{\"detail\":{\"message\":\"too many input items\",\"code\":\"invalid_input\"}}'"
            )
        return type("_Resp", (), {"vectors": [[1.0, 0.0] for _ in range(size)]})()

    monkeypatch.setattr(
        "cpm_builtin.embeddings.client.OpenAIEmbeddingsHttpClient.embed_texts",
        fake_embed_texts,
    )

    client = EmbeddingClient(base_url="http://127.0.0.1:8876", mode="http", timeout_s=1.0)
    vectors = client.embed_texts(
        ["a", "b", "c", "d", "e"],
        model_name="test-model",
        max_seq_length=128,
        normalize=False,
        dtype="float32",
        show_progress=False,
    )

    assert vectors.shape == (5, 2)
    assert any(size > 2 for size in calls)
    assert calls[-1] <= 2
    assert sum(1 for size in calls if size <= 2) >= 2


def test_embedding_client_respects_configured_input_size(monkeypatch) -> None:
    calls: list[int] = []

    def fake_embed_texts(self, texts, *, model=None, hints=None, extra=None, normalize=False):
        del self, model, hints, extra, normalize
        size = len(list(texts))
        calls.append(size)
        return type("_Resp", (), {"vectors": [[1.0, 0.0] for _ in range(size)]})()

    monkeypatch.setattr(
        "cpm_builtin.embeddings.client.OpenAIEmbeddingsHttpClient.embed_texts",
        fake_embed_texts,
    )

    client = EmbeddingClient(base_url="http://127.0.0.1:8876", mode="http", timeout_s=1.0, input_size=2)
    vectors = client.embed_texts(
        ["a", "b", "c", "d", "e"],
        model_name="test-model",
        max_seq_length=128,
        normalize=False,
        dtype="float32",
        show_progress=False,
    )

    assert vectors.shape == (5, 2)
    assert calls == [2, 2, 1]


def test_embedding_client_rejects_legacy_mode() -> None:
    with pytest.raises(ValueError, match="must be 'http'"):
        EmbeddingClient(base_url="http://127.0.0.1:8876", mode="legacy")


def test_embedding_client_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="must be 'http'"):
        EmbeddingClient(base_url="http://127.0.0.1:8876", mode="invalid")
