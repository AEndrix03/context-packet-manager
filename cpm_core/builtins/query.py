"""Built-in query command and native retriever wiring."""

from __future__ import annotations

import json
import os
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable, Protocol

from cpm_builtin.embeddings import EmbeddingClient, EmbeddingsConfigService
from cpm_builtin.packages import PackageManager, parse_package_spec
from cpm_builtin.packages.layout import version_dir
from cpm_core.api import CPMAbstractRetriever, cpmcommand, cpmretriever
from cpm_core.oci import read_install_lock, write_install_lock
from cpm_core.registry import CPMRegistryEntry, FeatureRegistry

from .commands import _WorkspaceAwareCommand

DEFAULT_RETRIEVER = "native-retriever"
_CONFIG_RETRIEVER_KEYS = ("retriever", "query_retriever", "default_retriever")
DEFAULT_EMBED_URL = "http://127.0.0.1:8876"
DEFAULT_EMBED_MODE = "http"
DEFAULT_INDEXER = "faiss-flatip"
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


_INDEXERS: dict[str, RetrievalIndexer] = {DEFAULT_INDEXER: FaissFlatIPIndexer()}
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

        try:
            vector = embedder.embed_texts(
                [query],
                model_name=model_name,
                max_seq_length=max_seq_length,
                normalize=True,
                dtype="float32",
                show_progress=False,
            )
            scores, ids = indexer.search(index=index, vector=vector, k=max(int(k), 1))
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

        hits: list[dict[str, Any]] = []
        for idx, score in zip(ids[0], scores[0]):
            if int(idx) < 0:
                continue
            if int(idx) >= len(docs):
                continue
            doc = docs[int(idx)]
            hits.append(
                {
                    "score": float(score),
                    "id": doc.get("id"),
                    "text": doc.get("text"),
                    "metadata": doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {},
                }
            )

        reranked_hits = reranker.rerank(query=query, hits=hits, k=int(k))
        warnings: list[str] = []
        score_values = [float(item.get("score")) for item in reranked_hits if isinstance(item.get("score"), (int, float))]
        if len(score_values) >= 2:
            score_range = max(score_values) - min(score_values)
            if score_range <= 1e-6:
                warnings.append(
                    "all top-k similarity scores are nearly identical; embeddings may be degenerate or constant"
                )

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
        parser.add_argument("--packet", required=True, help="Packet name or path")
        parser.add_argument("--query", required=True, help="Query text")
        parser.add_argument("-k", type=int, default=5, help="Number of results to retrieve")
        parser.add_argument("--retriever", help="Retriever name or group:name")
        parser.add_argument("--indexer", default=DEFAULT_INDEXER, help="Indexer strategy")
        parser.add_argument("--reranker", default=DEFAULT_RERANKER, help="Reranker strategy")
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

        packet_name = str(getattr(argv, "packet", "")).strip()
        install_lock = self._ensure_install_lock(workspace_root, packet_name)
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
            packet=str(argv.packet),
            query=str(argv.query),
            k=int(argv.k),
            cpm_dir=workspace_root,
            embed_url=resolved_embed_url,
            embed_mode=resolved_embed_mode,
            indexer=str(getattr(argv, "indexer", DEFAULT_INDEXER)),
            reranker=str(getattr(argv, "reranker", DEFAULT_RERANKER)),
            selected_model=str(install_lock.get("selected_model")) if install_lock else None,
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

    def _ensure_install_lock(self, workspace_root: Path, packet_name: str) -> dict[str, Any] | None:
        if not packet_name:
            return None
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
        warnings = payload.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                print(f"[cpm:query] warning={str(warning)}")
        for index, item in enumerate(payload.get("results", []), start=1):
            score = item.get("score")
            score_text = f"{float(score):.8f}" if isinstance(score, (int, float)) else "-"
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            path = metadata.get("path", "-")
            text = str(item.get("text", "")).replace("\n", " ").strip()
            print(f"[{index}] score={score_text} id={item.get('id', '-')} path={path} text={text}")


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
