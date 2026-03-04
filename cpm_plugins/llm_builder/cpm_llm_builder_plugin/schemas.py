"""Shared schemas for llm-builder pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence


def estimate_tokens(text: str) -> int:
    """Very rough token estimator used for local constraints.

    Improved with better handling for CJK characters and non-ASCII text.
    """
    cleaned = text.strip()
    if not cleaned:
        return 0
    ascii_chars = sum(1 for c in cleaned if ord(c) < 128)
    non_ascii = len(cleaned) - ascii_chars
    # CJK and similar: ~1 token per character
    return max(1, (ascii_chars // 4) + non_ascii)


def stable_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, Mapping):
                    return dict(parsed)
            except Exception:
                return {"raw": value}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            candidate = dict(value)  # type: ignore[arg-type]
            if isinstance(candidate, dict):
                return candidate
        except Exception:
            return {"items": list(value)}
    return {}


@dataclass(frozen=True)
class SourceDocument:
    path: str
    language: str
    mime: str
    source_hash: str


@dataclass(frozen=True)
class Window:
    """Represents a window of lines from a file sent to the LLM for chunking."""
    id: str
    path: str
    text: str
    start_line: int
    end_line: int
    language: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Window":
        return cls(
            id=str(payload.get("id", "")),
            path=str(payload.get("path", "")),
            text=str(payload.get("text", "")),
            start_line=int(payload.get("start_line", 1)),
            end_line=int(payload.get("end_line", 1)),
            language=str(payload.get("language", "")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Segment:
    id: str
    kind: str
    text: str
    start_line: int
    end_line: int
    symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "start": self.start_line,
            "end": self.end_line,
            "symbol": self.symbol,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Segment":
        return cls(
            id=str(payload["id"]),
            kind=str(payload.get("kind") or "segment"),
            text=str(payload.get("text") or ""),
            start_line=int(payload.get("start", 1)),
            end_line=int(payload.get("end", payload.get("start", 1))),
            symbol=str(payload["symbol"]) if payload.get("symbol") else None,
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    title: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()
    anchors: dict[str, Any] = field(default_factory=dict)
    relations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    window_id: str = ""
    chunk_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "tags": list(self.tags),
            "anchors": dict(self.anchors),
            "text": self.text,
            "relations": dict(self.relations),
            "metadata": dict(self.metadata),
            "window_id": self.window_id,
            "chunk_tokens": self.chunk_tokens,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Chunk":
        tags_raw = payload.get("tags") or []
        tags = tuple(str(item) for item in tags_raw if isinstance(item, str))
        text = str(payload.get("text") or "")
        return cls(
            id=str(payload.get("id") or ""),
            text=text,
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            tags=tags,
            anchors=_coerce_mapping(payload.get("anchors")),
            relations=_coerce_mapping(payload.get("relations")),
            metadata=_coerce_mapping(payload.get("metadata")),
            window_id=str(payload.get("window_id") or ""),
            chunk_tokens=int(payload.get("chunk_tokens") or estimate_tokens(text)),
        )


@dataclass(frozen=True)
class ChunkConstraints:
    max_chunk_tokens: int = 350
    min_chunk_tokens: int = 80
    max_segments_per_request: int = 6
    window_lines: int = 120
    overlap_lines: int = 5

    def to_dict(self) -> dict[str, int]:
        return {
            "max_chunk_tokens": int(self.max_chunk_tokens),
            "min_chunk_tokens": int(self.min_chunk_tokens),
            "max_segments_per_request": int(self.max_segments_per_request),
            "window_lines": int(self.window_lines),
            "overlap_lines": int(self.overlap_lines),
        }


def segment_cache_key(
    *,
    segment: Segment,
    model: str,
    prompt_version: str,
    constraints: ChunkConstraints,
) -> str:
    payload = {
        "segment": segment.to_dict(),
        "model": model,
        "prompt_version": prompt_version,
        "constraints": constraints.to_dict(),
    }
    return stable_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def normalize_chunk_list(payload: Any) -> list[Chunk]:
    """Convert legacy/OpenAI-like payloads to chunks."""

    raw_chunks: Any = None

    if isinstance(payload, list):
        raw_chunks = payload
    elif isinstance(payload, Mapping):
        if "chunks" in payload:
            raw_chunks = payload.get("chunks")
        elif "output" in payload:
            output = payload.get("output")
            if isinstance(output, Sequence):
                for item in output:
                    if not isinstance(item, Mapping):
                        continue
                    if item.get("type") != "output_json":
                        continue
                    json_payload = item.get("json")
                    if isinstance(json_payload, Mapping) and "chunks" in json_payload:
                        raw_chunks = json_payload.get("chunks")
                        break

    if not isinstance(raw_chunks, list):
        raise ValueError("LLM response does not contain chunk list")

    chunks: list[Chunk] = []
    for item in raw_chunks:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            chunks.append(Chunk(id="", text=text))
            continue
        if isinstance(item, Mapping):
            chunk = Chunk.from_dict(item)
            if chunk.text.strip():
                chunks.append(chunk)
    return chunks
