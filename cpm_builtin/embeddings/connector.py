from __future__ import annotations

import time
from typing import Iterable, Mapping, Sequence, TYPE_CHECKING

import numpy as np
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

from cpm_builtin.embeddings.config import EmbeddingProviderConfig
from cpm_builtin.embeddings.postprocess import is_l2_normalized, l2_normalize, prepare_embedding_matrix

if TYPE_CHECKING:
    from typing import Protocol

    class EmbeddingConnector(Protocol):
        def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
            ...
else:
    EmbeddingConnector = object  # type: ignore[assignment]


class HttpEmbeddingConnector:
    def __init__(
        self,
        provider: EmbeddingProviderConfig,
        *,
        max_retries: int = 2,
    ) -> None:
        self.provider = provider
        self.max_retries = max(1, max_retries)
        self._headers, self._auth = self._build_session_auth()
        self.endpoint = self._resolve_endpoint(
            provider.resolved_http_base_url,
            provider.resolved_http_path,
        )

    @staticmethod
    def _resolve_endpoint(base_url: str, path: str) -> str:
        base = base_url.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        if base.endswith(normalized_path):
            return base
        return f"{base}{normalized_path}"

    def _build_session_auth(self) -> tuple[dict[str, str], HTTPBasicAuth | None]:
        headers = self.provider.resolved_headers_static
        auth_entry = self.provider.auth
        auth_object: HTTPBasicAuth | None = None

        if isinstance(auth_entry, Mapping):
            auth_type = str(auth_entry.get("type", "")).lower()
            if auth_type == "basic":
                username = auth_entry.get("username") or ""
                password = auth_entry.get("password") or ""
                auth_object = HTTPBasicAuth(username, password)
            elif auth_type == "bearer":
                token = auth_entry.get("token")
                if token:
                    headers.setdefault("authorization", f"Bearer {token}")
        elif isinstance(auth_entry, str):
            headers.setdefault("authorization", f"Bearer {auth_entry}")

        headers.update(self._build_hint_headers())
        return headers, auth_object

    def _build_hint_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.provider.resolved_hint_dim is not None:
            headers["X-Embedding-Dim"] = str(self.provider.resolved_hint_dim)
        if self.provider.hint_normalize is not None:
            headers["X-Embedding-Normalize"] = (
                "true" if self.provider.hint_normalize else "false"
            )
        if self.provider.hint_task:
            headers["X-Embedding-Task"] = self.provider.hint_task
        if self.provider.resolved_hint_model:
            headers["X-Model-Hint"] = self.provider.resolved_hint_model
        return headers

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.provider.resolved_hint_dim or 0), dtype=np.float32)
        batch_size = max(1, self.provider.batch_size or len(texts))
        batches = [
            list(texts[i : i + batch_size]) for i in range(0, len(texts), batch_size)
        ]
        pieces: list[np.ndarray] = []
        for batch in batches:
            pieces.append(self._embed_batch(batch))
        return (
            np.vstack(pieces)
            if pieces
            else np.zeros((0, self.provider.resolved_hint_dim or 0), dtype=np.float32)
        )

    def _embed_batch(self, batch: list[str]) -> np.ndarray:
        timeout = self.provider.resolved_http_timeout or 10.0
        payload: dict[str, object] = {"texts": batch}
        if self.provider.resolved_hint_model:
            payload["model"] = self.provider.resolved_hint_model
        if self.provider.extra:
            payload["extra"] = self.provider.extra

        response = self._post_with_retry(payload, timeout)
        vectors = response.get("vectors") or []
        return self._prepare_array(vectors)

    def _post_with_retry(self, payload: Mapping[str, object], timeout: float) -> dict[str, object]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    self.endpoint,
                    json=payload,
                    headers=self._headers,
                    timeout=timeout,
                    auth=self._auth,
                )
                resp.raise_for_status()
                return resp.json()
            except RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
                time.sleep(min(attempt * 0.1, 1.0))
        raise RuntimeError("failed to send request") from last_error

    def _prepare_array(self, vectors: Sequence[Sequence[float]]) -> np.ndarray:
        mode = self.provider.normalize_mode
        if mode not in {"server", "client", "auto"}:
            raise ValueError("normalize_mode must be one of: server, client, auto")

        normalize_requested = self.provider.hint_normalize is True

        array, _dim = prepare_embedding_matrix(
            vectors,
            expected_dim=self.provider.resolved_hint_dim,
            normalize=False,
            fail_on_non_finite=True,
        )

        server_does_not_guarantee_normalized = (
            mode == "client" or (mode == "auto" and not is_l2_normalized(array))
        )
        if normalize_requested and server_does_not_guarantee_normalized:
            array = l2_normalize(array)
        return array
