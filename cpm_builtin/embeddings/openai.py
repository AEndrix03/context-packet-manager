from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import requests
from requests.exceptions import RequestException, Timeout

from .postprocess import l2_normalize
from .types import EmbedRequestIR, EmbedResponseIR

logger = logging.getLogger(__name__)


def _coerce_inputs(texts: str | Sequence[str]) -> list[str]:
    if isinstance(texts, str):
        return [texts]
    values = list(texts)
    for idx, value in enumerate(values):
        if not isinstance(value, str):
            raise TypeError(f"input[{idx}] must be str, got {type(value).__name__}")
    if not values:
        raise ValueError("input cannot be empty")
    return values


def _error_body_snippet(response: requests.Response, max_chars: int = 200) -> str:
    body = response.text or ""
    compact = " ".join(body.split())
    return compact[:max_chars]


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = (response.headers or {}).get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _build_hint_headers(
    hints: Mapping[str, Any] | None, *, model: str | None = None
) -> dict[str, str]:
    if not hints:
        return {}
    headers: dict[str, str] = {}
    dim = hints.get("dim")
    if dim is not None:
        headers["X-Embedding-Dim"] = str(int(dim))
    normalize = _coerce_optional_bool(hints.get("normalize"))
    if normalize is not None:
        headers["X-Embedding-Normalize"] = "true" if normalize else "false"
    task = hints.get("task")
    if task is not None:
        headers["X-Embedding-Task"] = str(task)
    model_hint = hints.get("model") if hints else None
    if model_hint is None:
        model_hint = model
    if model_hint is not None:
        headers["X-Model-Hint"] = str(model_hint)
    metadata = hints.get("metadata_b64")
    if metadata is not None:
        headers["X-CPM-Metadata"] = str(metadata)
    return headers


def serialize_openai_request(request: EmbedRequestIR) -> dict[str, Any]:
    payload: dict[str, Any] = {"input": _coerce_inputs(request.texts)}
    model = request.model or request.hints.get("model")
    if model:
        payload["model"] = str(model)
    payload.update(request.extra)
    return payload


def parse_openai_response(body: Mapping[str, Any]) -> EmbedResponseIR:
    data = body.get("data")
    if not isinstance(data, list):
        raise TypeError("response.data must be a list")

    indexed_vectors: list[tuple[int, list[float]]] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise TypeError("response.data entries must be mappings")
        if "index" not in item:
            raise ValueError("response.data entry missing 'index'")
        if "embedding" not in item:
            raise ValueError("response.data entry missing 'embedding'")
        index = item["index"]
        if not isinstance(index, int):
            raise TypeError("response.data entry index must be int")
        embedding = item["embedding"]
        if not isinstance(embedding, list):
            raise TypeError("response.data entry embedding must be a list")
        indexed_vectors.append((index, embedding))

    if not indexed_vectors:
        raise ValueError("response.data cannot be empty")

    indexed_vectors.sort(key=lambda item: item[0])
    expected = list(range(len(indexed_vectors)))
    actual = [index for index, _ in indexed_vectors]
    if actual != expected:
        raise ValueError("response.data indexes must be contiguous and start from 0")

    usage = body.get("usage")
    if usage is not None and not isinstance(usage, Mapping):
        raise TypeError("response.usage must be a mapping when present")

    model = body.get("model")
    if model is not None and not isinstance(model, str):
        raise TypeError("response.model must be a string when present")

    extra = {k: v for k, v in body.items() if k not in {"data", "model", "usage"}}
    return EmbedResponseIR(
        vectors=[embedding for _, embedding in indexed_vectors],
        model=model,
        usage=dict(usage) if isinstance(usage, Mapping) else None,
        extra=extra or None,
    )


def normalize_embeddings(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    matrix = np.asarray(vectors, dtype=np.float32)
    return l2_normalize(matrix).tolist()


class OpenAIEmbeddingsHttpClient:
    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.1,
        static_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.headers: dict[str, str] = {"content-type": "application/json"}
        if static_headers:
            self.headers.update({str(k): str(v) for k, v in static_headers.items()})
        if api_key:
            self.headers.setdefault("authorization", f"Bearer {api_key}")

    def embed_texts(
        self,
        texts: str | Sequence[str],
        *,
        model: str | None = None,
        hints: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
        normalize: bool = False,
    ) -> EmbedResponseIR:
        request = EmbedRequestIR(
            texts=_coerce_inputs(texts),
            model=model,
            hints=dict(hints or {}),
            extra=dict(extra or {}),
        )
        return self.embed(request, normalize=normalize)

    def embed(self, request: EmbedRequestIR, *, normalize: bool = False) -> EmbedResponseIR:
        payload = serialize_openai_request(request)
        hint_headers = _build_hint_headers(request.hints, model=request.model)
        headers = {**self.headers, **hint_headers}
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            retry_delay_seconds: float | None = None
            started_at = time.perf_counter()
            try:
                logger.info(
                    "openai embeddings request start attempt=%s/%s endpoint=%s model=%s count=%s",
                    attempt,
                    self.max_retries,
                    self.endpoint,
                    request.model,
                    len(request.texts),
                )
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                status = response.status_code
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                logger.info(
                    "openai embeddings request done attempt=%s/%s status=%s elapsed_ms=%.1f",
                    attempt,
                    self.max_retries,
                    status,
                    elapsed_ms,
                )
                if status == 429:
                    snippet = _error_body_snippet(response)
                    retry_after = _retry_after_seconds(response)
                    retry_delay_seconds = (
                        retry_after
                        if retry_after is not None
                        else max(1.0, min(self.backoff_seconds * attempt, 10.0))
                    )
                    raise RuntimeError(
                        f"rate limited (status={status}) payload_snippet='{snippet}'"
                    )
                if 400 <= status < 500:
                    snippet = _error_body_snippet(response)
                    logger.error(
                        "openai embeddings bad request status=%s payload_snippet='%s'",
                        status,
                        snippet,
                    )
                    raise ValueError(
                        f"bad request (status={status}) payload_snippet='{snippet}'"
                    )
                if 500 <= status < 600:
                    raise RuntimeError(f"upstream error status={status}")

                response.raise_for_status()
                parsed = parse_openai_response(response.json())
                parsed.validate_against_request(request)
                if not normalize:
                    return parsed
                return EmbedResponseIR(
                    vectors=normalize_embeddings(parsed.vectors),
                    model=parsed.model,
                    usage=parsed.usage,
                    extra=parsed.extra,
                )
            except Timeout as exc:
                last_error = exc
                logger.warning(
                    "openai embeddings timeout attempt=%s/%s",
                    attempt,
                    self.max_retries,
                )
            except RequestException as exc:
                last_error = exc
                logger.warning(
                    "openai embeddings transport error attempt=%s/%s: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
            except RuntimeError as exc:
                last_error = exc
                logger.warning(
                    "openai embeddings upstream/rate-limit error attempt=%s/%s: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
            except ValueError:
                raise

            if attempt < self.max_retries:
                delay_seconds = (
                    retry_delay_seconds
                    if retry_delay_seconds is not None
                    else min(self.backoff_seconds * attempt, 1.0)
                )
                logger.info(
                    "openai embeddings retry sleep attempt=%s/%s delay_seconds=%.2f",
                    attempt,
                    self.max_retries,
                    delay_seconds,
                )
                time.sleep(delay_seconds)

        raise RuntimeError("failed to obtain embeddings after retries") from last_error

