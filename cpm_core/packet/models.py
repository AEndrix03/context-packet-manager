from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping


@dataclass
class DocChunk:
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "text": self.text, "metadata": dict(self.metadata)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DocChunk":
        metadata = dict(data.get("metadata") or {})
        return cls(id=str(data["id"]), text=str(data["text"]), metadata=metadata)


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str | None
    model: str
    dim: int
    dtype: str
    normalized: bool
    max_seq_length: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "model": self.model,
            "dim": int(self.dim),
            "dtype": self.dtype,
            "normalized": self.normalized,
        }
        if self.provider:
            result["provider"] = self.provider
        if self.max_seq_length is not None:
            result["max_seq_length"] = int(self.max_seq_length)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EmbeddingSpec":
        model = data.get("model")
        if model is None:
            raise ValueError("manifest embedding entry is missing 'model'")
        dim = data.get("dim")
        if dim is None:
            raise ValueError("manifest embedding entry is missing 'dim'")
        dtype = data.get("dtype")
        if dtype is None:
            raise ValueError("manifest embedding entry is missing 'dtype'")
        normalized = data.get("normalized", False)
        max_seq = data.get("max_seq_length")
        provider = data.get("provider")
        return cls(
            provider=str(provider) if provider is not None else None,
            model=str(model),
            dim=int(dim),
            dtype=str(dtype),
            normalized=bool(normalized),
            max_seq_length=int(max_seq) if max_seq is not None else None,
        )


@dataclass
class PacketManifest:
    schema_version: str
    packet_id: str
    embedding: EmbeddingSpec
    similarity: Dict[str, Any] = field(default_factory=dict)
    files: Dict[str, Any] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)
    cpm: Dict[str, Any] = field(default_factory=dict)
    incremental: Dict[str, Any] = field(default_factory=dict)
    checksums: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PacketManifest":
        schema_version = str(data.get("schema_version") or "")
        packet_id = str(data.get("packet_id") or "")
        embedding = EmbeddingSpec.from_dict(data.get("embedding") or {})

        counts_raw = data.get("counts") or {}
        counts = {str(k): int(v) for k, v in counts_raw.items()}

        similarity = dict(data.get("similarity") or {})
        files = dict(data.get("files") or {})
        source = dict(data.get("source") or {})
        cpm = dict(data.get("cpm") or {})
        incremental = dict(data.get("incremental") or {})
        checksums = dict(data.get("checksums") or {})
        extras = {
            key: value
            for key, value in data.items()
            if key
            not in {
                "schema_version",
                "packet_id",
                "embedding",
                "similarity",
                "files",
                "counts",
                "source",
                "cpm",
                "incremental",
                "checksums",
            }
        }

        return cls(
            schema_version=schema_version,
            packet_id=packet_id,
            embedding=embedding,
            similarity=similarity,
            files=files,
            counts=counts,
            source=source,
            cpm=cpm,
            incremental=incremental,
            checksums=checksums,
            extras=extras,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "packet_id": self.packet_id,
            "embedding": self.embedding.to_dict(),
            "similarity": dict(self.similarity),
            "files": dict(self.files),
            "counts": dict(self.counts),
            "source": dict(self.source),
            "cpm": dict(self.cpm),
            "incremental": dict(self.incremental),
            "checksums": dict(self.checksums),
        }
        payload.update(self.extras)
        return payload
