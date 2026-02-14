"""Built-in query command and native retriever wiring."""

from __future__ import annotations

import hashlib
import json
import math
import os
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol

from cpm_builtin.embeddings import EmbeddingClient, EmbeddingsConfigService
from cpm_builtin.packages import PackageManager, parse_package_spec
from cpm_builtin.packages.layout import version_dir
from cpm_core.api import CPMAbstractRetriever, cpmcommand, cpmretriever
from cpm_core.hub import HubClient, load_hub_settings
from cpm_core.oci import read_install_lock, read_install_lock_as_of, write_install_lock
from cpm_core.policy import evaluate_policy, load_policy
from cpm_core.registry import CPMRegistryEntry, FeatureRegistry
from cpm_core.sources import SourceResolver

from .commands import _WorkspaceAwareCommand

DEFAULT_RETRIEVER = "native-retriever"
_CONFIG_RETRIEVER_KEYS = ("retriever", "query_retriever", "default_retriever")
DEFAULT_EMBED_URL = "http://127.0.0.1:8876"
DEFAULT_EMBED_MODE = "http"
DEFAULT_INDEXER = "faiss-flatip"
HYBRID_INDEXER = "hybrid-rrf"
DEFAULT_RERANKER = "none"


class RetrievalIndexer(Protocol):
    def search(self, *, index: Any, vector: Any, k: int) -> tuple[Any, Any]:
        ...


class RetrievalReranker(Protocol):
    def rerank(self, *, query: str, hits: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        ...


class FaissFlatIPIndexer:
    def search(self, *, index: Any, vector: Any, k: int) -> tuple[Any, Any]:
        return index.search(vector, max(int(k), 1))


class NoopReranker:
    def rerank(self, *, query: str, hits: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        del query
        return hits[: max(int(k), 1)]


class TokenDiversityReranker:
    def rerank(self, *, query: str, hits: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        del query
        target = max(int(k), 1)
        chosen: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        for hit in hits:
            text = str(hit.get("text", ""))
            tokens = {token for token in text.lower().split() if len(token) > 3}
            if not chosen:
                chosen.append(hit)
                seen_tokens.update(tokens)
            else:
                novelty = len(tokens - seen_tokens)
                if novelty > 0 or len(chosen) < target // 2:
                    chosen.append(hit)
                    seen_tokens.update(tokens)
            if len(chosen) >= target:
                break
        if len(chosen) < target:
            for hit in hits:
                if hit in chosen:
                    continue
                chosen.append(hit)
                if len(chosen) >= target:
                    break
        return chosen


_INDEXERS: dict[str, RetrievalIndexer] = {
    DEFAULT_INDEXER: FaissFlatIPIndexer(),
    HYBRID_INDEXER: FaissFlatIPIndexer(),
}
_RERANKERS: dict[str, RetrievalReranker] = {
    DEFAULT_RERANKER: NoopReranker(),
    "token-diversity": TokenDiversityReranker(),
}


def register_retriever_indexer(name: str, indexer: RetrievalIndexer) -> None:
    _INDEXERS[str(name).strip()] = indexer


def register_retriever_reranker(name: str, reranker: RetrievalReranker) -> None:
    _RERANKERS[str(name).strip()] = reranker


@cpmretriever(name=DEFAULT_RETRIEVER, group="cpm")
class NativeFaissRetriever(CPMAbstractRetriever):
    """Native FAISS retriever backed by packets installed in the workspace."""

    def retrieve(self, identifier: str, **kwargs: Any) -> dict[str, Any]:
        packet = str(kwargs.get("packet") or "").strip()
        if not packet:
            raise ValueError("packet is required")
        query = str(identifier)
        k = int(kwargs.get("k", 5))
        cpm_dir = Path(str(kwargs.get("cpm_dir") or ".cpm"))
        embed_url = str(kwargs.get("embed_url") or os.environ.get("RAG_EMBED_URL") or DEFAULT_EMBED_URL)
        embed_mode = str(kwargs.get("embed_mode") or os.environ.get("RAG_EMBED_MODE") or DEFAULT_EMBED_MODE)
        indexer_name = str(kwargs.get("indexer") or DEFAULT_INDEXER).strip()
        reranker_name = str(kwargs.get("reranker") or DEFAULT_RERANKER).strip()
        indexer = _INDEXERS.get(indexer_name)
        reranker = _RERANKERS.get(reranker_name)
        if indexer is None:
            return {
                "ok": False,
                "error": "invalid_indexer",
                "detail": f"indexer '{indexer_name}' is not registered",
                "available_indexers": sorted(_INDEXERS.keys()),
            }
        if reranker is None:
            return {
                "ok": False,
                "error": "invalid_reranker",
                "detail": f"reranker '{reranker_name}' is not registered",
                "available_rerankers": sorted(_RERANKERS.keys()),
            }
        packet_dir = self._resolve_packet_dir(cpm_dir, packet)
        if packet_dir is None:
            return {
                "ok": False,
                "error": "packet_not_found",
                "packet": packet,
                "tried": str((cpm_dir / "packages" / packet).resolve()).replace("\\", "/"),
            }

        manifest_path = packet_dir / "manifest.json"
        if not manifest_path.exists():
            return {
                "ok": False,
                "error": "packet_not_found",
                "detail": f"missing manifest at {manifest_path}",
                "packet": packet,
            }
        docs_path = packet_dir / "docs.jsonl"
        if not docs_path.exists():
            return {
                "ok": False,
                "error": "packet_not_found",
                "detail": f"missing docs.jsonl at {docs_path}",
                "packet": packet,
            }
        index_path = packet_dir / "faiss" / "index.faiss"
        if not index_path.exists():
            return {
                "ok": False,
                "error": "packet_not_found",
                "detail": f"missing faiss index at {index_path}",
                "packet": packet,
            }

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        embedding_cfg = manifest.get("embedding") or {}
        model_name = str(kwargs.get("selected_model") or embedding_cfg.get("model") or "").strip()
        if not model_name:
            return {
                "ok": False,
                "error": "invalid_manifest",
                "detail": "manifest.embedding.model is required",
                "packet": packet,
            }
        max_seq_length = int(embedding_cfg.get("max_seq_length", 1024))
        docs = self._load_docs(docs_path)
        try:
            import faiss

            index = faiss.read_index(str(index_path))
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "ok": False,
                "error": "retrieval_failed",
                "detail": str(exc),
                "packet": packet,
            }

        embedder = EmbeddingClient(embed_url, mode=embed_mode)
        if not embedder.health():
            return {
                "ok": False,
                "error": "embed_server_unreachable",
                "embed_url": embed_url,
                "embed_mode": embed_mode,
                "hint": "configure an embedding provider with `cpm embed add ... --set-default` or set RAG_EMBED_URL/RAG_EMBED_MODE",
            }

        warnings: list[str] = []
        try:
            vector = embedder.embed_texts(
                [query],
                model_name=model_name,
                max_seq_length=max_seq_length,
                normalize=True,
                dtype="float32",
                show_progress=False,
            )
            dense_k = max(int(k), 1)
            if indexer_name == HYBRID_INDEXER:
                dense_k = max(int(k) * 4, 20)
            scores, ids = indexer.search(index=index, vector=vector, k=dense_k)
        except FileNotFoundError:
            return {
                "ok": False,
                "error": "retrieval_failed",
                "detail": "required packet artifacts are missing",
                "packet": packet,
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "ok": False,
                "error": "retrieval_failed",
                "detail": str(exc),
                "packet": packet,
            }

        dense_hits: list[dict[str, Any]] = []
        for rank, (idx, score) in enumerate(zip(ids[0], scores[0]), start=1):
            if int(idx) < 0:
                continue
            if int(idx) >= len(docs):
                continue
            doc = docs[int(idx)]
            dense_hits.append(
                {
                    "score": float(score),
                    "id": doc.get("id"),
                    "text": doc.get("text"),
                    "metadata": doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {},
                    "_dense_rank": rank,
                    "_doc_idx": int(idx),
                }
            )

        hits = dense_hits
        if indexer_name == HYBRID_INDEXER:
            sparse_index_path = packet_dir / "sparse" / "bm25.json"
            sparse_hits, sparse_warning = _bm25_hits(
                query=query,
                docs=docs,
                k=max(int(k) * 4, 20),
                sparse_index_path=sparse_index_path,
            )
            if sparse_warning:
                warnings.append(sparse_warning)
            hits = _fuse_rrf(dense_hits, sparse_hits, k=int(k))

        reranked_hits = reranker.rerank(query=query, hits=hits, k=int(k))
        score_values = [float(item.get("score")) for item in reranked_hits if isinstance(item.get("score"), (int, float))]
        if len(score_values) >= 2:
            score_range = max(score_values) - min(score_values)
            if score_range <= 1e-6:
                warnings.append(
                    "all top-k similarity scores are nearly identical; embeddings may be degenerate or constant"
                )

        max_tokens = int(kwargs.get("max_context_tokens", 6000))
        compiled_context = _compile_context(
            query=query,
            hits=reranked_hits,
            max_tokens=max_tokens,
            warnings=warnings,
        )
        output_hash = hashlib.sha256(
            json.dumps(
                {
                    "packet": str(packet_dir),
                    "query": query,
                    "indexer": indexer_name,
                    "reranker": reranker_name,
                    "results": reranked_hits,
                    "compiled_context": compiled_context,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        return {
            "ok": True,
            "packet": packet_dir.parent.name,
            "packet_version": packet_dir.name,
            "packet_path": str(packet_dir).replace("\\", "/"),
            "query": query,
            "k": int(k),
            "embedding": {
                "model": model_name,
                "max_seq_length": max_seq_length,
                "embed_url": embed_url,
                "mode": embed_mode,
            },
            "indexer": indexer_name,
            "reranker": reranker_name,
            "results": reranked_hits,
            "compiled_context": compiled_context,
            "output_hash": output_hash,
            "warnings": warnings,
        }

    @staticmethod
    def _resolve_packet_dir(cpm_dir: Path, packet: str) -> Path | None:
        candidate = Path(packet)
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
        manager = PackageManager(cpm_dir)
        name, explicit_version = parse_package_spec(packet)
        if not name:
            return None
        try:
            resolved = manager.resolve_version(name, explicit_version)
        except ValueError:
            return None
        target = version_dir(cpm_dir, name, resolved)
        if not target.exists():
            return None
        return target.resolve()

    @staticmethod
    def _load_docs(path: Path) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                payload = line.strip()
                if not payload:
                    continue
                try:
                    record = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    docs.append(record)
        return docs


@cpmcommand(name="query", group="cpm")
class QueryCommand(_WorkspaceAwareCommand):
    """Query packets for relevant context using native or plugin retrievers."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument("--packet", help="Packet name or path")
        parser.add_argument("--source", help="Source URI (dir://, oci://, https://...)")
        parser.add_argument("--query", required=True, help="Query text")
        parser.add_argument("--as-of", help="Historical snapshot timestamp (ISO or YYYY-MM-DD)")
        parser.add_argument("-k", type=int, default=5, help="Number of results to retrieve")
        parser.add_argument("--retriever", help="Retriever name or group:name")
        parser.add_argument("--indexer", default=DEFAULT_INDEXER, help="Indexer strategy")
        parser.add_argument("--reranker", default=DEFAULT_RERANKER, help="Reranker strategy")
        parser.add_argument("--max-context-tokens", type=int, default=6000, help="Context compiler token cap")
        parser.add_argument("--replay-log", help="Write deterministic replay log to this path")
        parser.add_argument("--embed-url", help="Embedding server URL override")
        parser.add_argument(
            "--embeddings-mode",
            choices=["http"],
            help="Embedding transport mode override",
        )
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Output format",
        )

    def run(self, argv: Any) -> int:
        requested_dir = getattr(argv, "workspace_dir", None)
        workspace_root = self._resolve(requested_dir)
        self.workspace_root = workspace_root
        policy = load_policy(workspace_root)
        hub_client = HubClient(load_hub_settings(workspace_root))

        source_uri = str(getattr(argv, "source", "") or "").strip()
        packet_name = str(getattr(argv, "packet", "")).strip()
        if not packet_name and not source_uri:
            print("[cpm:query] either --packet or --source is required")
            return 1

        resolved_reference: dict[str, Any] | None = None
        if source_uri:
            source_policy = evaluate_policy(policy, source_uri=source_uri)
            if not source_policy.allow:
                print(f"[cpm:query] policy deny source={source_uri} reason={source_policy.reason}")
                return 1
            remote_source_policy = hub_client.evaluate_policy(
                {"source_uri": source_uri, "trust_score": 1.0, "strict_failures": []},
                _policy_payload(policy),
            )
            if isinstance(remote_source_policy, dict) and not bool(remote_source_policy.get("allow", True)):
                reason = str(remote_source_policy.get("reason") or "unknown")
                print(f"[cpm:query] hub policy deny source={source_uri} reason={reason}")
                return 1
            try:
                reference, local_packet = SourceResolver(workspace_root).resolve_and_fetch(source_uri)
            except Exception as exc:
                print(f"[cpm:query] unable to materialize source '{source_uri}': {exc}")
                return 1
            packet_name = str(local_packet.path)
            resolved_reference = {
                "uri": reference.uri,
                "resolved_uri": reference.resolved_uri,
                "digest": reference.digest,
                "cache_key": local_packet.cache_key,
                "cached": local_packet.cached,
                "trust_score": reference.metadata.get("trust_score"),
                "verification": reference.metadata.get("verification"),
                "refs": reference.metadata.get("refs"),
                "trust": reference.metadata.get("trust"),
            }
            trust_failures = []
            verification = reference.metadata.get("verification")
            if isinstance(verification, dict):
                candidate_failures = verification.get("strict_failures")
                if isinstance(candidate_failures, list):
                    trust_failures = [str(item) for item in candidate_failures]
            trust_eval = evaluate_policy(
                policy,
                source_uri=source_uri,
                trust_score=float(reference.metadata.get("trust_score") or 0.0),
                strict_failures=trust_failures,
            )
            if not trust_eval.allow:
                print(f"[cpm:query] policy deny source={source_uri} reason={trust_eval.reason}")
                return 1
            remote_trust_eval = hub_client.evaluate_policy(
                {
                    "source_uri": source_uri,
                    "trust_score": float(reference.metadata.get("trust_score") or 0.0),
                    "strict_failures": trust_failures,
                },
                _policy_payload(policy),
            )
            if isinstance(remote_trust_eval, dict) and not bool(remote_trust_eval.get("allow", True)):
                reason = str(remote_trust_eval.get("reason") or "unknown")
                print(f"[cpm:query] hub policy deny source={source_uri} reason={reason}")
                return 1
            if trust_eval.decision == "warn":
                for warning in trust_eval.warnings:
                    print(f"[cpm:query] warning={warning}")

        as_of_value = str(getattr(argv, "as_of", "") or "").strip()
        install_lock = None if source_uri else self._ensure_install_lock(workspace_root, packet_name, as_of=as_of_value)
        if as_of_value and install_lock:
            lock_name = str(install_lock.get("name") or packet_name).strip()
            lock_version = str(install_lock.get("version") or "").strip()
            if lock_name and lock_version:
                packet_name = f"{lock_name}@{lock_version}"
        requested = self._requested_retriever(argv, workspace_root, install_lock=install_lock)
        entries = self._load_retriever_entries(workspace_root)

        explicit_retriever = bool(getattr(argv, "retriever", None))
        suggested_retriever = None
        if not explicit_retriever and install_lock and install_lock.get("suggested_retriever"):
            suggested_retriever = str(install_lock.get("suggested_retriever")).strip() or None

        entry = self._resolve_retriever_entry(
            entries,
            requested,
            quiet=bool(suggested_retriever and requested == suggested_retriever and not explicit_retriever),
        )
        if entry is None and not explicit_retriever and suggested_retriever and requested == suggested_retriever:
            print(
                f"[cpm:query] suggested retriever '{suggested_retriever}' is not installed; "
                f"install the plugin providing it, then retry. Falling back to '{DEFAULT_RETRIEVER}'."
            )
            entry = self._resolve_retriever_entry(entries, DEFAULT_RETRIEVER)
        elif entry is None and not explicit_retriever and requested != DEFAULT_RETRIEVER:
            print(f"[cpm:query] retriever '{requested}' unavailable; fallback to default '{DEFAULT_RETRIEVER}'")
            entry = self._resolve_retriever_entry(entries, DEFAULT_RETRIEVER)
        if entry is None:
            return 1

        resolved_embed_url, resolved_embed_mode = self._resolve_embedding_transport(
            workspace_root=workspace_root,
            embed_url=getattr(argv, "embed_url", None),
            embed_mode=getattr(argv, "embeddings_mode", None),
        )

        payload = self._invoke_retriever(
            entry=entry,
            packet=packet_name,
            query=str(argv.query),
            k=int(argv.k),
            cpm_dir=workspace_root,
            embed_url=resolved_embed_url,
            embed_mode=resolved_embed_mode,
            indexer=str(getattr(argv, "indexer", DEFAULT_INDEXER)),
            reranker=str(getattr(argv, "reranker", DEFAULT_RERANKER)),
            selected_model=str(install_lock.get("selected_model")) if install_lock else None,
            max_context_tokens=int(getattr(argv, "max_context_tokens", policy.max_tokens)),
        )
        if resolved_reference:
            payload["source"] = resolved_reference

        compiled = payload.get("compiled_context")
        if isinstance(compiled, dict):
            token_count = int(compiled.get("token_estimate") or 0)
            context_policy = evaluate_policy(policy, token_count=token_count)
            if not context_policy.allow:
                payload = {
                    "ok": False,
                    "error": "policy_denied",
                    "detail": context_policy.reason,
                    "packet": payload.get("packet"),
                    "query": payload.get("query"),
                    "k": payload.get("k"),
                }
            remote_context_policy = hub_client.evaluate_policy(
                {"source_uri": source_uri or None, "trust_score": 1.0, "strict_failures": [], "token_count": token_count},
                _policy_payload(policy),
            )
            if isinstance(remote_context_policy, dict) and not bool(remote_context_policy.get("allow", True)):
                payload = {
                    "ok": False,
                    "error": "hub_policy_denied",
                    "detail": str(remote_context_policy.get("reason") or "unknown"),
                    "packet": payload.get("packet"),
                    "query": payload.get("query"),
                    "k": payload.get("k"),
                }

        self._write_replay_log(
            workspace_root=workspace_root,
            payload=payload,
            packet=packet_name,
            query=str(argv.query),
            indexer=str(getattr(argv, "indexer", DEFAULT_INDEXER)),
            reranker=str(getattr(argv, "reranker", DEFAULT_RERANKER)),
            selected_model=str(install_lock.get("selected_model")) if install_lock else None,
            source=resolved_reference,
            explicit_log_path=str(getattr(argv, "replay_log", "") or "").strip() or None,
        )

        if getattr(argv, "format", "text") == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0 if payload.get("ok", True) else 1

        self._print_text(payload, retriever_name=entry.qualified_name)
        return 0 if payload.get("ok", True) else 1

    def _requested_retriever(
        self,
        argv: Any,
        workspace_root: Path,
        *,
        install_lock: dict[str, Any] | None,
    ) -> str:
        explicit = getattr(argv, "retriever", None)
        if explicit:
            return str(explicit)
        if install_lock and install_lock.get("suggested_retriever"):
            return str(install_lock.get("suggested_retriever"))
        for key in _CONFIG_RETRIEVER_KEYS:
            configured = self.resolver.resolve_setting(key, start_dir=workspace_root)
            if configured:
                return configured
        return DEFAULT_RETRIEVER

    def _load_retriever_entries(self, workspace_root: Path) -> list[CPMRegistryEntry]:
        from cpm_core.app import CPMApp

        app = CPMApp(start_dir=workspace_root)
        app.bootstrap()
        return [entry for entry in app.feature_registry.entries() if entry.kind == "retriever"]

    def _resolve_retriever_entry(
        self,
        entries: Iterable[CPMRegistryEntry],
        requested: str,
        *,
        quiet: bool = False,
    ) -> CPMRegistryEntry | None:
        pool = list(entries)
        if not pool:
            print("[cpm:query] no retrievers are registered")
            return None

        if ":" in requested:
            for entry in pool:
                if entry.qualified_name == requested:
                    return entry
            if not quiet:
                print(f"[cpm:query] retriever '{requested}' is not registered")
            return None

        matches = [entry for entry in pool if entry.name == requested]
        if not matches:
            if not quiet:
                print(f"[cpm:query] retriever '{requested}' is not registered")
                available = ", ".join(sorted(entry.qualified_name for entry in pool))
                print(f"[cpm:query] available retrievers: {available}")
            return None
        if len(matches) > 1:
            if not quiet:
                names = ", ".join(sorted(entry.qualified_name for entry in matches))
                print(
                    f"[cpm:query] retriever '{requested}' is ambiguous ({names}); use group:name"
                )
            return None
        return matches[0]

    def _invoke_retriever(
        self,
        *,
        entry: CPMRegistryEntry,
        packet: str,
        query: str,
        k: int,
        cpm_dir: Path,
        embed_url: str | None,
        embed_mode: str | None,
        indexer: str,
        reranker: str,
        selected_model: str | None,
        max_context_tokens: int,
    ) -> dict[str, Any]:
        retriever = entry.target()
        call_attempts = (
            lambda: retriever.retrieve(
                query,
                k=k,
                packet=packet,
                cpm_dir=str(cpm_dir),
                embed_url=embed_url,
                embed_mode=embed_mode,
                indexer=indexer,
                reranker=reranker,
                selected_model=selected_model,
                max_context_tokens=max_context_tokens,
            ),
            lambda: retriever.retrieve(query, k=k, packet=packet),
            lambda: retriever.retrieve(query, k=k),
            lambda: retriever.retrieve(query),
        )
        for attempt in call_attempts:
            try:
                raw = attempt()
                return _normalize_payload(raw, packet=packet, query=query, k=k)
            except TypeError:
                continue
            except Exception as exc:  # pragma: no cover - defensive
                return {
                    "ok": False,
                    "error": "retrieval_failed",
                    "detail": str(exc),
                    "packet": packet,
                    "query": query,
                    "k": k,
                }
        return {
            "ok": False,
            "error": "retriever_signature_mismatch",
            "detail": f"{entry.qualified_name} does not expose a compatible retrieve() signature",
            "packet": packet,
            "query": query,
            "k": k,
        }

    def _resolve_embedding_transport(
        self,
        *,
        workspace_root: Path,
        embed_url: str | None,
        embed_mode: str | None,
    ) -> tuple[str | None, str | None]:
        resolved_url = str(embed_url).strip() if embed_url is not None else None
        resolved_mode = str(embed_mode).strip().lower() if embed_mode is not None else None
        if resolved_url and resolved_mode:
            return resolved_url, resolved_mode

        service = EmbeddingsConfigService(workspace_root)
        default_provider = service.default_provider()
        if default_provider is None:
            return resolved_url, resolved_mode

        if not resolved_url:
            resolved_url = default_provider.url
        if not resolved_mode:
            resolved_mode = str(default_provider.type).strip().lower() or DEFAULT_EMBED_MODE
        return resolved_url, resolved_mode

    def _ensure_install_lock(
        self,
        workspace_root: Path,
        packet_name: str,
        *,
        as_of: str | None = None,
    ) -> dict[str, Any] | None:
        if not packet_name:
            return None
        if as_of:
            parsed_as_of = _parse_as_of(as_of)
            if parsed_as_of is None:
                return None
            historical = read_install_lock_as_of(workspace_root, packet_name, as_of=parsed_as_of)
            if historical:
                return historical
        existing = read_install_lock(workspace_root, packet_name)
        if existing:
            return existing

        packet_dir = self._resolve_packet_dir_for_lock(workspace_root, packet_name)
        if packet_dir is None:
            return None
        manifest_path = packet_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        embedding = manifest.get("embedding") if isinstance(manifest.get("embedding"), dict) else {}
        model_name = str(embedding.get("model") or "").strip()
        if not model_name:
            return None
        suggested = None
        extras = manifest.get("extras")
        if isinstance(extras, dict):
            suggested = extras.get("suggested_retriever")
        if suggested is None:
            suggested = manifest.get("suggested_retriever")
        default_provider = EmbeddingsConfigService(workspace_root).default_provider()
        payload = {
            "name": packet_name,
            "version": packet_dir.name,
            "selected_model": model_name,
            "selected_provider": default_provider.name if default_provider else None,
            "suggested_retriever": str(suggested).strip() if suggested else None,
            "auto_resolved_by_query": True,
            "sources": [],
            "trust_score": 0.0,
        }
        write_install_lock(workspace_root, packet_name, payload)
        return payload

    def _resolve_packet_dir_for_lock(self, workspace_root: Path, packet: str) -> Path | None:
        direct = Path(packet)
        if direct.is_dir():
            return direct.resolve()
        if direct.exists():
            return direct.parent.resolve()

        manager = PackageManager(workspace_root)
        try:
            name, version = parse_package_spec(packet)
            resolved = manager.resolve_version(name, version)
            return version_dir(workspace_root, name, resolved)
        except Exception:
            return None

    def _print_text(self, payload: dict[str, Any], *, retriever_name: str) -> None:
        if not payload.get("ok", True):
            error = payload.get("error", "unknown_error")
            detail = payload.get("detail")
            print(f"[cpm:query] error={error}")
            if detail:
                print(f"[cpm:query] detail={detail}")
            hint = payload.get("hint")
            if hint:
                print(f"[cpm:query] hint={hint}")
            return

        print(
            f"[cpm:query] retriever={retriever_name} packet={payload.get('packet')} k={payload.get('k')} "
            f"indexer={payload.get('indexer', DEFAULT_INDEXER)} reranker={payload.get('reranker', DEFAULT_RERANKER)}"
        )
        source_data = payload.get("source")
        if isinstance(source_data, dict):
            print(
                f"[cpm:query] source={source_data.get('uri')} digest={source_data.get('digest')} "
                f"cache_key={source_data.get('cache_key')} cached={source_data.get('cached')}"
            )
        warnings = payload.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                print(f"[cpm:query] warning={str(warning)}")
        compiled_context = payload.get("compiled_context")
        if isinstance(compiled_context, dict):
            print(
                f"[cpm:query] context tokens={compiled_context.get('token_estimate')} "
                f"snippets={len(compiled_context.get('core_snippets', []))}"
            )
        if payload.get("output_hash"):
            print(f"[cpm:query] output_hash={payload.get('output_hash')}")
        for index, item in enumerate(payload.get("results", []), start=1):
            score = item.get("score")
            score_text = f"{float(score):.8f}" if isinstance(score, (int, float)) else "-"
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            path = metadata.get("path", "-")
            text = str(item.get("text", "")).replace("\n", " ").strip()
            print(f"[{index}] score={score_text} id={item.get('id', '-')} path={path} text={text}")

    def _write_replay_log(
        self,
        *,
        workspace_root: Path,
        payload: dict[str, Any],
        packet: str,
        query: str,
        indexer: str,
        reranker: str,
        selected_model: str | None,
        source: dict[str, Any] | None,
        explicit_log_path: str | None,
    ) -> None:
        output_hash = str(payload.get("output_hash") or "").strip()
        if not output_hash:
            return
        record = {
            "schema": "cpm.replay.v1",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "packet": packet,
            "query": query,
            "indexer": indexer,
            "reranker": reranker,
            "selected_model": selected_model,
            "source": source or {},
            "output_hash": output_hash,
        }
        if explicit_log_path:
            path = Path(explicit_log_path)
        else:
            root = workspace_root / "state" / "replay"
            root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            path = root / f"query-{stamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_payload(raw: Any, *, packet: str, query: str, k: int) -> dict[str, Any]:
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("ok", True)
        payload.setdefault("packet", packet)
        payload.setdefault("query", query)
        payload.setdefault("k", k)
        payload.setdefault("indexer", DEFAULT_INDEXER)
        payload.setdefault("reranker", DEFAULT_RERANKER)
        results = payload.get("results")
        if isinstance(results, list):
            payload["results"] = [_normalize_hit(item) for item in results]
        else:
            payload["results"] = []
        return payload

    if isinstance(raw, list):
        return {
            "ok": True,
            "packet": packet,
            "query": query,
            "k": k,
            "indexer": DEFAULT_INDEXER,
            "reranker": DEFAULT_RERANKER,
            "results": [_normalize_hit(item) for item in raw],
        }

    return {
        "ok": True,
        "packet": packet,
        "query": query,
        "k": k,
        "indexer": DEFAULT_INDEXER,
        "reranker": DEFAULT_RERANKER,
        "results": [
            {
                "score": None,
                "id": None,
                "text": str(raw),
                "metadata": {},
            }
        ],
    }


def _normalize_hit(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            "score": item.get("score"),
            "id": item.get("id"),
            "text": item.get("text", ""),
            "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        }
    return {"score": None, "id": None, "text": str(item), "metadata": {}}


def _parse_as_of(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    candidates = [raw]
    if len(raw) == 10:
        candidates.append(f"{raw}T23:59:59+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _bm25_hits(
    *,
    query: str,
    docs: list[dict[str, Any]],
    k: int,
    sparse_index_path: Path,
) -> tuple[list[dict[str, Any]], str | None]:
    terms = [token for token in query.lower().split() if token]
    if not terms:
        return [], None
    if not sparse_index_path.exists():
        # Build on-the-fly when sparse artifact is not present to preserve fallback.
        return _build_bm25_from_docs(terms=terms, docs=docs, k=k), "sparse_index_missing_fallback_runtime"
    try:
        payload = json.loads(sparse_index_path.read_text(encoding="utf-8"))
    except Exception:
        return _build_bm25_from_docs(terms=terms, docs=docs, k=k), "sparse_index_invalid_fallback_runtime"
    idf = payload.get("idf") if isinstance(payload.get("idf"), dict) else {}
    doc_len = payload.get("doc_len") if isinstance(payload.get("doc_len"), list) else []
    tf = payload.get("tf") if isinstance(payload.get("tf"), list) else []
    avgdl = float(payload.get("avgdl", 1.0) or 1.0)
    if not tf or not doc_len:
        return _build_bm25_from_docs(terms=terms, docs=docs, k=k), "sparse_index_empty_fallback_runtime"
    scores: list[tuple[int, float]] = []
    k1 = 1.2
    b = 0.75
    for idx, (doc_tf, length) in enumerate(zip(tf, doc_len)):
        if not isinstance(doc_tf, dict):
            continue
        score = 0.0
        for term in terms:
            term_tf = float(doc_tf.get(term, 0.0))
            if term_tf <= 0:
                continue
            denom = term_tf + k1 * (1.0 - b + b * (float(length) / avgdl))
            score += float(idf.get(term, 0.0)) * ((term_tf * (k1 + 1.0)) / max(denom, 1e-6))
        if score > 0:
            scores.append((idx, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    hits = []
    for rank, (idx, score) in enumerate(scores[: max(k, 1)], start=1):
        if idx >= len(docs):
            continue
        doc = docs[idx]
        hits.append(
            {
                "score": float(score),
                "id": doc.get("id"),
                "text": doc.get("text"),
                "metadata": doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {},
                "_sparse_rank": rank,
                "_doc_idx": idx,
            }
        )
    return hits, None


def _build_bm25_from_docs(*, terms: list[str], docs: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    tokenized = [str(doc.get("text") or "").lower().split() for doc in docs]
    doc_count = max(len(tokenized), 1)
    avgdl = sum(len(tokens) for tokens in tokenized) / doc_count
    df: dict[str, int] = {}
    for tokens in tokenized:
        unique = set(tokens)
        for token in unique:
            df[token] = df.get(token, 0) + 1
    idf = {
        term: math.log(1 + (doc_count - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
        for term in terms
    }
    k1 = 1.2
    b = 0.75
    scores: list[tuple[int, float]] = []
    for idx, tokens in enumerate(tokenized):
        counts: dict[str, int] = {}
        for token in tokens:
            if token in idf:
                counts[token] = counts.get(token, 0) + 1
        score = 0.0
        for term in terms:
            tf = float(counts.get(term, 0))
            if tf <= 0:
                continue
            denom = tf + k1 * (1.0 - b + b * (len(tokens) / max(avgdl, 1e-6)))
            score += idf.get(term, 0.0) * ((tf * (k1 + 1.0)) / max(denom, 1e-6))
        if score > 0:
            scores.append((idx, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    hits = []
    for rank, (idx, score) in enumerate(scores[: max(k, 1)], start=1):
        doc = docs[idx]
        hits.append(
            {
                "score": float(score),
                "id": doc.get("id"),
                "text": doc.get("text"),
                "metadata": doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {},
                "_sparse_rank": rank,
                "_doc_idx": idx,
            }
        )
    return hits


def _fuse_rrf(
    dense_hits: list[dict[str, Any]],
    sparse_hits: list[dict[str, Any]],
    *,
    k: int,
) -> list[dict[str, Any]]:
    by_doc: dict[int, dict[str, Any]] = {}
    for index, hit in enumerate(dense_hits, start=1):
        doc_idx = int(hit.get("_doc_idx", -1))
        if doc_idx < 0:
            continue
        score = 1.0 / (60.0 + float(hit.get("_dense_rank") or index))
        current = by_doc.setdefault(doc_idx, dict(hit))
        current["_rrf_score"] = float(current.get("_rrf_score", 0.0)) + score
    for index, hit in enumerate(sparse_hits, start=1):
        doc_idx = int(hit.get("_doc_idx", -1))
        if doc_idx < 0:
            continue
        score = 1.0 / (60.0 + float(hit.get("_sparse_rank") or index))
        current = by_doc.setdefault(doc_idx, dict(hit))
        current["_rrf_score"] = float(current.get("_rrf_score", 0.0)) + score
        if "text" not in current:
            current["text"] = hit.get("text")
        if "metadata" not in current:
            current["metadata"] = hit.get("metadata")
        if "id" not in current:
            current["id"] = hit.get("id")
    ranked = sorted(by_doc.values(), key=lambda item: float(item.get("_rrf_score", 0.0)), reverse=True)
    output: list[dict[str, Any]] = []
    for item in ranked[: max(k, 1)]:
        output.append(
            {
                "score": float(item.get("_rrf_score", 0.0)),
                "id": item.get("id"),
                "text": item.get("text"),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
    return output


def _compile_context(
    *,
    query: str,
    hits: list[dict[str, Any]],
    max_tokens: int,
    warnings: list[str],
) -> dict[str, Any]:
    budget = max(int(max_tokens), 1)
    used = 0
    core_snippets: list[dict[str, Any]] = []
    glossary: list[str] = []
    seen_terms: set[str] = set()
    for hit in hits:
        text = str(hit.get("text") or "").strip()
        if not text:
            continue
        citation = _citation_for_hit(hit)
        snippet_tokens = _estimate_tokens(text)
        if used + snippet_tokens > budget:
            continue
        core_snippets.append(
            {
                "id": hit.get("id"),
                "text": text,
                "score": hit.get("score"),
                "citation": citation,
            }
        )
        used += snippet_tokens
        for token in text.split():
            cleaned = token.strip(".,:;!?()[]{}\"'").lower()
            if len(cleaned) < 6 or cleaned in seen_terms:
                continue
            seen_terms.add(cleaned)
            glossary.append(cleaned)
            if len(glossary) >= 12:
                break
        if used >= budget:
            break
    outline = [f"Answer query: {query}", "Ground on retrieved snippets", "Include citations for each snippet"]
    citations = [item["citation"] for item in core_snippets]
    risks = list(warnings)
    if not core_snippets:
        risks.append("no_snippets_within_budget")
    return {
        "outline": outline,
        "core_snippets": core_snippets,
        "glossary": glossary,
        "risks": risks,
        "citations": citations,
        "token_estimate": used,
    }


def _citation_for_hit(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    path = str(metadata.get("path") or "").strip()
    if path:
        return path
    identifier = str(hit.get("id") or "").strip()
    if identifier:
        return f"id:{identifier}"
    return "unknown"


def _estimate_tokens(text: str) -> int:
    words = len([token for token in text.split() if token])
    return max(1, int(words * 1.3))


def _policy_payload(policy: Any) -> dict[str, Any]:
    return {
        "mode": str(getattr(policy, "mode", "strict")),
        "allowed_sources": list(getattr(policy, "allowed_sources", ())),
        "min_trust_score": float(getattr(policy, "min_trust_score", 0.0)),
        "max_tokens": int(getattr(policy, "max_tokens", 6000)),
    }


def register_builtin_retrievers(registry: FeatureRegistry) -> None:
    """Register the native retriever(s) with the supplied registry."""

    metadata = getattr(NativeFaissRetriever, "__cpm_feature__", None)
    if metadata is None:
        return
    registry.register(
        CPMRegistryEntry(
            group=metadata["group"],
            name=str(metadata["name"]),
            target=NativeFaissRetriever,
            kind=str(metadata["kind"]),
            origin="builtin",
        )
    )
