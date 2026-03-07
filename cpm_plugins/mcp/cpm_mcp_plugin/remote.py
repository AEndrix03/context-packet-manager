"""Remote-first MCP tool implementations built on core resolver/query logic."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cpm_builtin.embeddings import EmbeddingClient
from cpm_core.build.builder import Embedder, embed_packet_from_chunks
from cpm_core.sources.models import LocalPacket, PacketReference
from cpm_core.sources.resolver import SourceResolver

from .env import MCPSettings, load_settings

logger = logging.getLogger(__name__)
_LOOKUP_ALIAS_TTL_SECONDS = 180
_MAX_LOOKUP_CANDIDATES = 3
_MAX_QUERY_K = 20


class _HttpEmbedder(Embedder):
    def __init__(self, url: str, *, mode: str = "http") -> None:
        self._client = EmbeddingClient(url, mode=mode)

    def health(self) -> bool:
        return bool(self._client.health())

    def embed_texts(
        self,
        texts: list[str],
        *,
        model_name: str,
        max_seq_length: int,
        normalize: bool,
        dtype: str,
        show_progress: bool,
    ):
        return self._client.embed_texts(
            texts,
            model_name=model_name,
            max_seq_length=max_seq_length,
            normalize=normalize,
            dtype=dtype,
            show_progress=show_progress,
        )


@dataclass(frozen=True)
class QueryMaterialization:
    digest: str
    source_uri: str
    pinned_uri: str
    payload_dir: Path
    index_dir: Path
    metadata_path: Path
    cache_hit: bool


def lookup_remote(
    *,
    name: str | None = None,
    version: str | None = None,
    alias: str | None = "latest",
    entrypoint: str | None = None,
    kind: str | None = None,
    capability: str | list[str] | None = None,
    os_name: str | None = None,
    arch: str | None = None,
    registry: str | None = None,
    ref: str | None = None,
    k: int = _MAX_LOOKUP_CANDIDATES,
    cpm_root: str | None = None,
) -> dict[str, Any]:
    settings = load_settings(cpm_root=cpm_root, registry=registry)
    source_uri = _build_lookup_source_uri(
        ref=ref,
        registry=registry or settings.registry,
        name=name,
        version=version,
        alias=alias,
    )
    if not source_uri:
        return {
            "ok": False,
            "error": "invalid_lookup_input",
            "detail": "REGISTRY not set and no oci:// ref provided",
        }
    normalized_capabilities = _normalize_capabilities(capability)

    cache_hit, cached_payload = _read_alias_lookup_cache(
        root=settings.cpm_root,
        source_uri=source_uri,
        is_alias=bool(alias and not version and not ref),
    )
    if cache_hit and isinstance(cached_payload, dict):
        _lookup_log(
            root=settings.cpm_root,
            event="lookup_cache_hit",
            payload={"source_uri": source_uri},
        )
        return cached_payload

    resolver = SourceResolver(settings.cpm_root)
    attempt_uris = [source_uri, *_lookup_fallback_source_uris(source_uri)]
    attempted: list[str] = []
    failures: list[str] = []
    for attempt_uri in attempt_uris:
        if attempt_uri in attempted:
            continue
        attempted.append(attempt_uri)
        _lookup_log(
            root=settings.cpm_root,
            event="lookup_attempt",
            payload={"source_uri": attempt_uri, "attempt": len(attempted)},
        )
        started = time.monotonic()
        try:
            reference, metadata = resolver.lookup_metadata(attempt_uri)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            detail = str(exc)
            failures.append(f"{attempt_uri} -> {detail}")
            logger.warning("lookup attempt failed source_uri=%s elapsed_ms=%s detail=%s", attempt_uri, elapsed_ms, detail)
            _lookup_log(
                root=settings.cpm_root,
                event="lookup_attempt_failed",
                payload={"source_uri": attempt_uri, "elapsed_ms": elapsed_ms, "detail": detail},
            )
            continue

        candidates = _build_lookup_candidates(reference=reference, metadata=metadata)
        filtered = _filter_candidates(
            candidates=candidates,
            entrypoint=entrypoint,
            kind=kind,
            capabilities=normalized_capabilities,
            os_name=os_name,
            arch=arch,
        )
        if not filtered:
            return {
                "ok": False,
                "error": "no_match",
                "detail": _build_no_match_detail(
                    entrypoint=entrypoint,
                    kind=kind,
                    capabilities=normalized_capabilities,
                    os_name=os_name,
                    arch=arch,
                ),
            }

        shortlist = filtered[: max(1, min(int(k or 1), _MAX_LOOKUP_CANDIDATES))]
        payload: dict[str, Any] = {
            "ok": True,
            "source_uri": source_uri,
            "resolved_source_uri": attempt_uri,
            "count": len(shortlist),
            "candidates": shortlist,
            "selected": shortlist[0],
        }
        _write_alias_lookup_cache(
            root=settings.cpm_root,
            source_uri=source_uri,
            payload=payload,
            is_alias=bool(alias and not version and not ref),
        )
        _lookup_log(
            root=settings.cpm_root,
            event="lookup_success",
            payload={"source_uri": attempt_uri, "count": len(shortlist)},
        )
        return payload

    hint = _build_lookup_failure_hint(attempted)
    detail_parts = []
    if failures:
        detail_parts.append(" | ".join(failures[-2:]))
    if hint:
        detail_parts.append(hint)
    detail = " ; ".join(part for part in detail_parts if part) or "lookup attempts failed"
    _lookup_log(
        root=settings.cpm_root,
        event="lookup_failed",
        payload={"source_uri": source_uri, "attempted": attempted, "detail": detail},
    )
    return {"ok": False, "error": "lookup_failed", "detail": detail}


def query_remote(
    *,
    ref: str,
    q: str,
    k: int = 5,
    rerank: bool = True,
    registry: str | None = None,
    cpm_root: str | None = None,
) -> dict[str, Any]:
    settings = load_settings(cpm_root=cpm_root, registry=registry)
    source_uri = _build_query_source_uri(ref=ref, registry=registry or settings.registry)
    if not source_uri:
        return {
            "ok": False,
            "error": "invalid_query_input",
            "detail": "REGISTRY not set and query ref is not an oci:// URI",
        }

    try:
        materialized = _materialize_for_query(settings=settings, source_uri=source_uri)
    except Exception as exc:
        return {"ok": False, "error": "materialize_failed", "detail": str(exc)}

    try:
        _ensure_query_index(settings=settings, materialized=materialized)
    except Exception as exc:
        return {"ok": False, "error": "index_failed", "detail": str(exc), "digest": materialized.digest}

    retriever = _build_native_retriever()
    result = retriever.retrieve(
        q,
        packet=str(materialized.payload_dir),
        k=max(1, min(int(k), _MAX_QUERY_K)),
        cpm_dir=str(settings.cpm_root),
        embed_url=settings.embedding_url,
        embed_mode=settings.embedding_mode,
        selected_model=settings.embedding_model,
        indexer="hybrid-rrf",
        reranker="cpm:cross-encoder" if rerank else "none",
    )
    compressed = _compress_query_results(result.get("results") if isinstance(result, dict) else [])
    payload: dict[str, Any] = {
        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "source_uri": materialized.source_uri,
        "pinned_uri": materialized.pinned_uri,
        "digest": materialized.digest,
        "cache": {"hit": materialized.cache_hit},
        "query": q,
        "k": max(1, min(int(k), _MAX_QUERY_K)),
        "results": compressed,
    }
    if isinstance(result, dict) and not bool(result.get("ok")):
        payload["error"] = str(result.get("error") or "retrieval_failed")
        if result.get("detail"):
            payload["detail"] = str(result.get("detail"))
    return payload


def plan_from_intent(
    *,
    intent: str,
    constraints: dict[str, Any] | None = None,
    name_hint: str | None = None,
    version: str | None = None,
    registry: str | None = None,
    cpm_root: str | None = None,
) -> dict[str, Any]:
    constraints = constraints or {}
    intent_mode = _intent_mode(intent=intent, constraints=constraints)
    packet_name = name_hint or str(constraints.get("name") or "").strip() or _extract_name_hint(intent)
    if not packet_name:
        return {
            "ok": False,
            "error": "name_hint_required",
            "detail": "provide name_hint or constraints.name for deterministic planning",
        }

    lookup_payload = lookup_remote(
        name=packet_name,
        version=version or str(constraints.get("version") or "").strip() or None,
        alias=str(constraints.get("alias") or "latest"),
        entrypoint=str(constraints.get("entrypoint") or "").strip() or None,
        kind=str(constraints.get("kind") or "").strip() or None,
        capability=constraints.get("capability"),
        os_name=str(constraints.get("os") or "").strip() or None,
        arch=str(constraints.get("arch") or "").strip() or None,
        registry=registry,
        cpm_root=cpm_root,
        k=3,
    )
    if not lookup_payload.get("ok"):
        return lookup_payload

    candidates = list(lookup_payload.get("candidates") or [])
    scored = []
    for candidate in candidates:
        score = _score_candidate_from_intent(candidate=candidate, intent=intent, constraints=constraints)
        scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("pinned_uri") or "")))
    ranked = [item[1] for item in scored]

    if intent_mode == "query" and len(scored) >= 2 and scored[0][0] == scored[1][0]:
        for idx in range(min(2, len(ranked))):
            probe = query_remote(
                ref=str(ranked[idx].get("pinned_uri") or ""),
                q=intent,
                k=3,
                registry=registry,
                cpm_root=cpm_root,
            )
            evidence_bonus = len(list(probe.get("results") or []))
            scored[idx] = (scored[idx][0] + evidence_bonus, ranked[idx])
        scored.sort(key=lambda item: (-item[0], str(item[1].get("pinned_uri") or "")))
        ranked = [item[1] for item in scored]

    selected = []
    for candidate in ranked[:2]:
        selected_entrypoint = _select_plan_entrypoint(candidate=candidate, constraints=constraints, intent_mode=intent_mode)
        selected.append(
            {
                "pinned_uri": candidate.get("pinned_uri"),
                "entrypoint": selected_entrypoint,
                "args_template": _build_plan_args_template(
                    candidate=candidate,
                    selected_entrypoint=selected_entrypoint,
                ),
                "why": _why_candidate(candidate, intent, intent_mode=intent_mode),
            }
        )
    fallbacks = []
    for candidate in ranked[2:4]:
        selected_entrypoint = _select_plan_entrypoint(candidate=candidate, constraints=constraints, intent_mode=intent_mode)
        fallbacks.append(
            {
                "pinned_uri": candidate.get("pinned_uri"),
                "entrypoint": selected_entrypoint,
                "args_template": _build_plan_args_template(
                    candidate=candidate,
                    selected_entrypoint=selected_entrypoint,
                ),
            }
        )
    return {
        "ok": True,
        "intent_mode": intent_mode,
        "selected": selected,
        "fallbacks": fallbacks,
        "constraints_applied": constraints,
    }


def evidence_digest(
    *,
    ref: str,
    question: str,
    k: int = 6,
    max_chars: int = 1200,
    registry: str | None = None,
    cpm_root: str | None = None,
) -> dict[str, Any]:
    query_payload = query_remote(ref=ref, q=question, k=max(1, min(int(k), _MAX_QUERY_K)), registry=registry, cpm_root=cpm_root)
    if not query_payload.get("ok"):
        return query_payload
    deduped = []
    seen = set()
    for item in list(query_payload.get("results") or []):
        key = (str(item.get("path") or ""), str(item.get("snippet") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    compressed = []
    used = 0
    for item in deduped:
        snippet = str(item.get("snippet") or "")
        budget = max(int(max_chars), 64)
        if used >= budget:
            break
        room = budget - used
        final_snippet = snippet[:room].strip()
        if not final_snippet:
            continue
        used += len(final_snippet)
        compressed.append({**item, "snippet": final_snippet})

    summary_lines = []
    for item in compressed[:6]:
        path = str(item.get("path") or "-")
        snippet = str(item.get("snippet") or "")
        summary_lines.append(f"- {path}: {snippet}")

    return {
        "ok": True,
        "ref": ref,
        "question": question,
        "digest": query_payload.get("digest"),
        "pinned_uri": query_payload.get("pinned_uri"),
        "evidence": compressed,
        "summary": "\n".join(summary_lines),
    }


def _materialize_for_query(*, settings: MCPSettings, source_uri: str) -> QueryMaterialization:
    digest_hint = _parse_digest(source_uri)
    fingerprint = _embedding_fingerprint(settings)
    if digest_hint:
        safe = _safe_key(digest_hint)
        payload_dir = settings.cpm_root / "cas" / safe / "payload"
        index_dir = settings.cpm_root / "index" / safe / fingerprint
        metadata_path = settings.cpm_root / "meta" / safe / "packet.manifest.json"
        if payload_dir.exists() and (index_dir / "index.faiss").exists():
            return QueryMaterialization(
                digest=digest_hint,
                source_uri=source_uri,
                pinned_uri=_pin_source_uri(source_uri, digest_hint),
                payload_dir=payload_dir,
                index_dir=index_dir,
                metadata_path=metadata_path,
                cache_hit=True,
            )

    resolver = SourceResolver(settings.cpm_root)
    reference, local_packet = resolver.resolve_and_fetch(source_uri)
    safe = _safe_key(reference.digest)
    payload_dir = settings.cpm_root / "cas" / safe / "payload"
    index_dir = settings.cpm_root / "index" / safe / fingerprint
    metadata_path = settings.cpm_root / "meta" / safe / "packet.manifest.json"
    _mirror_payload(local_packet=local_packet, payload_dir=payload_dir)
    _write_local_metadata(payload_dir=payload_dir, metadata_path=metadata_path)
    return QueryMaterialization(
        digest=reference.digest,
        source_uri=source_uri,
        pinned_uri=_pin_source_uri(source_uri, reference.digest),
        payload_dir=payload_dir,
        index_dir=index_dir,
        metadata_path=metadata_path,
        cache_hit=False,
    )


def _build_native_retriever() -> Any:
    # Import lazily to avoid re-exporting decorated feature classes from plugin modules.
    from cpm_core.builtins.query import NativeFaissRetriever

    return NativeFaissRetriever()


def _ensure_query_index(*, settings: MCPSettings, materialized: QueryMaterialization) -> None:
    index_file = materialized.index_dir / "index.faiss"
    payload_index = materialized.payload_dir / "faiss" / "index.faiss"
    materialized.index_dir.mkdir(parents=True, exist_ok=True)
    lock_path = materialized.index_dir / ".lock"
    _acquire_lock(lock_path)
    try:
        if index_file.exists() and not payload_index.exists():
            payload_index.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(index_file, payload_index)

        if payload_index.exists() and not index_file.exists():
            shutil.copy2(payload_index, index_file)
            payload_vectors = materialized.payload_dir / "vectors.f16.bin"
            cached_vectors = materialized.index_dir / "vectors.f16.bin"
            if payload_vectors.exists() and not cached_vectors.exists():
                shutil.copy2(payload_vectors, cached_vectors)
            return

        if index_file.exists() and payload_index.exists():
            return

        if settings.embedding_url is None:
            raise ValueError("EMBEDDING_URL is required when precomputed faiss index is missing")
        model_name = _resolve_model_for_rebuild(materialized.payload_dir, settings.embedding_model)
        embedder = _HttpEmbedder(settings.embedding_url, mode=settings.embedding_mode)
        if not embedder.health():
            raise ValueError(f"embedding server unreachable at {settings.embedding_url} (mode={settings.embedding_mode})")
        manifest = embed_packet_from_chunks(
            materialized.payload_dir,
            model_name=model_name,
            max_seq_length=1024,
            archive=False,
            archive_format="zip",
            embedder=embedder,
            builder_name="cpm:mcp-query",
        )
        if manifest is None:
            raise ValueError("unable to generate index from docs.jsonl")
        if not payload_index.exists():
            raise ValueError("index generation completed without faiss/index.faiss")
        shutil.copy2(payload_index, index_file)
        payload_vectors = materialized.payload_dir / "vectors.f16.bin"
        if payload_vectors.exists():
            shutil.copy2(payload_vectors, materialized.index_dir / "vectors.f16.bin")
    finally:
        _release_lock(lock_path)


def _build_lookup_candidates(*, reference: PacketReference, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    packet = metadata.get("packet") if isinstance(metadata.get("packet"), dict) else {}
    compat = metadata.get("compat") if isinstance(metadata.get("compat"), dict) else {}
    tags = packet.get("tags") if isinstance(packet.get("tags"), list) else []
    capabilities = packet.get("capabilities") if isinstance(packet.get("capabilities"), list) else []
    entrypoints = packet.get("entrypoints") if isinstance(packet.get("entrypoints"), list) else []
    resolved_ref = str(reference.metadata.get("ref") or "")
    digest_ref = resolved_ref.split("@", 1)[0]
    if ":" in digest_ref:
        digest_ref = digest_ref.rsplit(":", 1)[0]
    pinned_uri = f"oci://{digest_ref}@{reference.digest}"
    return [
        {
            "pinned_uri": pinned_uri,
            "name": str(packet.get("name") or ""),
            "version": str(packet.get("version") or ""),
            "entrypoints": [_entrypoint_name(item) for item in entrypoints if _entrypoint_name(item)],
            "tags": [str(item) for item in tags if str(item).strip()],
            "kind": str(packet.get("kind") or ""),
            "capabilities": [str(item) for item in capabilities if str(item).strip()],
            "compat": {
                "os": [str(item) for item in list(compat.get("os") or []) if str(item).strip()],
                "arch": [str(item) for item in list(compat.get("arch") or []) if str(item).strip()],
            },
            "metadata_digest": reference.metadata.get("metadata_digest"),
        }
    ]


def _filter_candidates(
    *,
    candidates: list[dict[str, Any]],
    entrypoint: str | None,
    kind: str | None,
    capabilities: list[str],
    os_name: str | None,
    arch: str | None,
) -> list[dict[str, Any]]:
    filtered = []
    requested_entrypoint = str(entrypoint or "").strip()
    requested_kind = str(kind or "").strip()
    requested_os = str(os_name or "").strip()
    requested_arch = str(arch or "").strip()
    for candidate in candidates:
        if requested_kind and requested_kind != str(candidate.get("kind") or ""):
            continue
        if requested_entrypoint and requested_entrypoint not in list(candidate.get("entrypoints") or []):
            continue
        candidate_caps = [str(item) for item in list(candidate.get("capabilities") or [])]
        if any(capability not in candidate_caps for capability in capabilities):
            continue
        compat = candidate.get("compat") if isinstance(candidate.get("compat"), dict) else {}
        compat_os = [str(item) for item in list(compat.get("os") or [])]
        compat_arch = [str(item) for item in list(compat.get("arch") or [])]
        if requested_os and compat_os and requested_os not in compat_os:
            continue
        if requested_arch and compat_arch and requested_arch not in compat_arch:
            continue
        filtered.append(candidate)
    filtered.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("version") or ""), str(item.get("pinned_uri") or "")))
    return filtered


def _build_lookup_source_uri(
    *,
    ref: str | None,
    registry: str | None,
    name: str | None,
    version: str | None,
    alias: str | None,
) -> str:
    explicit_ref = str(ref or "").strip()
    if explicit_ref.startswith("oci://"):
        return explicit_ref
    if explicit_ref:
        reg = str(registry or "").strip().rstrip("/")
        if not reg:
            return ""
        return f"oci://{reg}/{explicit_ref.lstrip('/')}"
    packet_name = str(name or "").strip()
    reg = str(registry or "").strip().rstrip("/")
    if not reg or not packet_name:
        return ""
    tag = str(version or alias or "latest").strip() or "latest"
    return f"oci://{reg}/{packet_name}:{tag}"


def _build_query_source_uri(*, ref: str, registry: str | None) -> str:
    value = str(ref or "").strip()
    if value.startswith("oci://"):
        return value
    reg = str(registry or "").strip().rstrip("/")
    if not reg:
        return ""
    return f"oci://{reg}/{value.lstrip('/')}"


def _parse_digest(uri: str) -> str | None:
    value = str(uri or "").strip()
    if "@sha256:" not in value:
        return None
    digest = value.rsplit("@", 1)[-1]
    if digest.startswith("sha256:"):
        return digest
    return None


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _pin_source_uri(source_uri: str, digest: str) -> str:
    value = source_uri[len("oci://") :] if source_uri.startswith("oci://") else source_uri
    base = value.split("@", 1)[0]
    if ":" in base.rsplit("/", 1)[-1]:
        base = base.rsplit(":", 1)[0]
    return f"oci://{base}@{digest}"


def _embedding_fingerprint(settings: MCPSettings) -> str:
    base = f"{settings.embedding_url or ''}|{settings.embedding_model or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _mirror_payload(*, local_packet: LocalPacket, payload_dir: Path) -> None:
    if payload_dir.exists():
        return
    payload_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(local_packet.path, payload_dir)


def _write_local_metadata(*, payload_dir: Path, metadata_path: Path) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    packet_manifest = payload_dir / "packet.manifest.json"
    if packet_manifest.exists():
        shutil.copy2(packet_manifest, metadata_path)
        return
    manifest = payload_dir / "manifest.json"
    if manifest.exists():
        parsed = json.loads(manifest.read_text(encoding="utf-8"))
        packet = parsed.get("cpm") if isinstance(parsed.get("cpm"), dict) else {}
        normalized = {
            "schema": "cpm.packet.metadata",
            "schema_version": "1.0",
            "packet": {
                "name": str(packet.get("name") or payload_dir.parent.name),
                "version": str(packet.get("version") or payload_dir.name),
            },
            "payload": {"files": []},
        }
        metadata_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_model_for_rebuild(payload_dir: Path, override_model: str | None) -> str:
    candidate = str(override_model or "").strip()
    if candidate:
        return candidate
    manifest_path = payload_dir / "manifest.json"
    if manifest_path.exists():
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        embedding = parsed.get("embedding") if isinstance(parsed.get("embedding"), dict) else {}
        model = str(embedding.get("model") or "").strip()
        if model:
            return model
    raise ValueError("EMBEDDING_MODEL is required when manifest.embedding.model is missing")


def _acquire_lock(lock_path: Path, timeout_s: float = 30.0, poll_s: float = 0.05) -> None:
    start = time.time()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            if time.time() - start >= timeout_s:
                raise TimeoutError(f"timeout acquiring lock {lock_path}") from None
            time.sleep(poll_s)


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        return


def _compress_query_results(results: Any) -> list[dict[str, Any]]:
    output = []
    if not isinstance(results, list):
        return output
    for item in results:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        snippet = str(item.get("text") or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300].rstrip() + "..."
        output.append(
            {
                "score": float(item.get("score") or 0.0),
                "path": str(metadata.get("path") or metadata.get("source") or metadata.get("file") or item.get("id") or ""),
                "start": metadata.get("start") or metadata.get("line_start"),
                "end": metadata.get("end") or metadata.get("line_end"),
                "snippet": snippet,
            }
        )
    return output


def _normalize_capabilities(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    tokenized = [segment.strip() for segment in str(value).split(",")]
    return [segment for segment in tokenized if segment]


def _build_no_match_detail(
    *,
    entrypoint: str | None,
    kind: str | None,
    capabilities: list[str],
    os_name: str | None,
    arch: str | None,
) -> str:
    parts = []
    if entrypoint:
        parts.append(f"entrypoint={entrypoint}")
    if kind:
        parts.append(f"kind={kind}")
    for capability in capabilities:
        parts.append(f"capability={capability}")
    if os_name:
        parts.append(f"os={os_name}")
    if arch:
        parts.append(f"arch={arch}")
    return "No matches for filters: " + ", ".join(parts) if parts else "No matches for requested packet"


def _entrypoint_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return ""


def _read_alias_lookup_cache(*, root: Path, source_uri: str, is_alias: bool) -> tuple[bool, dict[str, Any] | None]:
    if not is_alias:
        return False, None
    path = root / "cache" / "metadata_alias" / f"{_safe_key(source_uri)}.json"
    if not path.exists():
        return False, None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, None
    expires_at = float(parsed.get("expires_at") or 0)
    if expires_at <= time.time():
        return False, None
    payload = parsed.get("payload")
    if not isinstance(payload, dict):
        return False, None
    return True, payload


def _write_alias_lookup_cache(*, root: Path, source_uri: str, payload: dict[str, Any], is_alias: bool) -> None:
    if not is_alias:
        return
    path = root / "cache" / "metadata_alias" / f"{_safe_key(source_uri)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"expires_at": time.time() + _LOOKUP_ALIAS_TTL_SECONDS, "payload": payload}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _lookup_fallback_source_uris(source_uri: str) -> list[str]:
    if not source_uri.startswith("oci://"):
        return []
    value = source_uri[len("oci://") :]
    if "/" not in value:
        return []
    host, rest = value.split("/", 1)
    lowered_host = host.lower()
    aliases: list[str] = []
    if lowered_host == "localhost":
        aliases.append(f"host.docker.internal/{rest}")
    elif lowered_host.startswith("localhost:"):
        aliases.append(f"host.docker.internal:{host.split(':', 1)[1]}/{rest}")
    elif lowered_host == "127.0.0.1":
        aliases.append(f"host.docker.internal/{rest}")
    elif lowered_host.startswith("127.0.0.1:"):
        aliases.append(f"host.docker.internal:{host.split(':', 1)[1]}/{rest}")
    elif lowered_host == "host.docker.internal":
        aliases.append(f"localhost/{rest}")
    elif lowered_host.startswith("host.docker.internal:"):
        aliases.append(f"localhost:{host.split(':', 1)[1]}/{rest}")
    return [f"oci://{candidate}" for candidate in aliases if f"oci://{candidate}" != source_uri]


def _build_lookup_failure_hint(attempted_uris: list[str]) -> str:
    if any("localhost" in uri for uri in attempted_uris):
        return "If MCP runs in an isolated runtime, try REGISTRY=host.docker.internal:<port>."
    if any("host.docker.internal" in uri for uri in attempted_uris):
        return "If host.docker.internal is unreachable, try REGISTRY=localhost:<port>."
    return ""


def _lookup_log(*, root: Path, event: str, payload: dict[str, Any]) -> None:
    try:
        path = root / "logs" / "mcp-lookup.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": int(time.time()), "event": event, **payload}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        logger.debug("failed to write lookup log event=%s", event, exc_info=True)


def _extract_name_hint(intent: str) -> str | None:
    marker = "packet:"
    lowered = intent.lower()
    if marker not in lowered:
        return None
    start = lowered.index(marker) + len(marker)
    tail = intent[start:].strip()
    if not tail:
        return None
    token = tail.split()[0].strip().strip(",.")
    return token or None


def _intent_mode(*, intent: str, constraints: dict[str, Any]) -> str:
    forced = str(constraints.get("mode") or "").strip().lower()
    if forced in {"lookup", "query"}:
        return forced

    requested_entrypoint = str(constraints.get("entrypoint") or "").strip().lower()
    if requested_entrypoint in {"lookup", "query"}:
        return requested_entrypoint

    lowered_intent = str(intent).lower()
    lookup_score = 0
    query_score = 0

    if any(token in lowered_intent for token in ("lookup", "metadata", "catalog", "latest", "version", "entrypoint", "capabilit", "tag", "alias")):
        lookup_score += 2
    if any(token in lowered_intent for token in ("search", "question", "answer", "snippet", "context", "where", "how", "why", "what")):
        query_score += 1

    for key in ("kind", "capability", "os", "arch", "version", "alias"):
        value = constraints.get(key)
        if value:
            lookup_score += 1

    if query_score > lookup_score:
        return "query"
    return "lookup"


def _score_candidate_from_intent(*, candidate: dict[str, Any], intent: str, constraints: dict[str, Any]) -> int:
    score = 0
    lowered_intent = intent.lower()
    entrypoint = str(constraints.get("entrypoint") or "").strip()
    if entrypoint and entrypoint in list(candidate.get("entrypoints") or []):
        score += 5
    kind = str(candidate.get("kind") or "")
    if kind and kind.lower() in lowered_intent:
        score += 2
    for capability in list(candidate.get("capabilities") or []):
        if str(capability).lower() in lowered_intent:
            score += 1
    return score


def _select_plan_entrypoint(*, candidate: dict[str, Any], constraints: dict[str, Any], intent_mode: str) -> str:
    if intent_mode == "lookup":
        return "lookup"
    selected = _select_entrypoint(candidate, constraints)
    return selected or "query"


def _build_plan_args_template(*, candidate: dict[str, Any], selected_entrypoint: str) -> dict[str, Any]:
    if selected_entrypoint == "lookup":
        return {"ref": candidate.get("pinned_uri"), "k": 3}
    return {"ref": candidate.get("pinned_uri"), "q": "{question}", "k": 5}


def _select_entrypoint(candidate: dict[str, Any], constraints: dict[str, Any]) -> str | None:
    requested = str(constraints.get("entrypoint") or "").strip()
    entrypoints = [str(item) for item in list(candidate.get("entrypoints") or [])]
    if requested and requested in entrypoints:
        return requested
    return entrypoints[0] if entrypoints else None


def _why_candidate(candidate: dict[str, Any], intent: str, *, intent_mode: str) -> str:
    name = str(candidate.get("name") or "")
    version = str(candidate.get("version") or "")
    caps = ", ".join(str(item) for item in list(candidate.get("capabilities") or [])[:3]) or "no capabilities"
    return f"selected {name}@{version} for {intent_mode} intent '{intent[:64]}' with capabilities [{caps}]"
