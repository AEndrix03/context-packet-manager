from __future__ import annotations

import time
from typing import Iterable, Mapping, Sequence, TYPE_CHECKING

import numpy as np
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

from cpm_builtin.embeddings.config import EmbeddingProviderConfig

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
        base = provider.url.rstrip("/")
        self.endpoint = f"{base}/embed"

    def _build_session_auth(self) -> tuple[dict[str, str], HTTPBasicAuth | None]:
        headers = {str(k): str(v) for k, v in self.provider.headers.items()}
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

        return headers, auth_object

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.provider.dims or 0), dtype=np.float32)
        batch_size = max(1, self.provider.batch_size or len(texts))
        batches = [
            list(texts[i : i + batch_size]) for i in range(0, len(texts), batch_size)
        ]
        pieces: list[np.ndarray] = []
        for batch in batches:
            pieces.append(self._embed_batch(batch))
        return np.vstack(pieces) if pieces else np.zeros((0, self.provider.dims or 0), dtype=np.float32)

    def _embed_batch(self, batch: list[str]) -> np.ndarray:
        timeout = float(self.provider.timeout) if self.provider.timeout else 10.0
        payload: dict[str, object] = {"texts": batch}
        if self.provider.model:
            payload["model"] = self.provider.model
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
        dims = self.provider.dims
        if not vectors:
            return np.zeros((0, dims or 0), dtype=np.float32)
        expected = len(vectors[0])
        if dims and expected != dims:
            raise ValueError("response vector does not match expected dims")
        for row in vectors:
            if len(row) != expected:
                raise ValueError("inconsistent vector dimensions")
            if dims and len(row) != dims:
                raise ValueError("vector length does not line up with config dims")
        array = np.asarray(vectors, dtype=np.float32)
        if dims and array.shape[1] != dims:
            raise ValueError("final embedding matrix geometry mismatch")
        return array
