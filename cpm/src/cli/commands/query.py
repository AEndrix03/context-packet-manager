import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

import faiss
import numpy as np

from cli.core.cpm_pkg import resolve_current_packet_dir
from embedding.http_embedder import HttpEmbedder


CACHE_SCHEMA_VERSION = 1

MetadataFilters = Sequence[Tuple[str, str]]
EmbedderFactory = Callable[[str], "EmbedderProtocol"]


class EmbedderProtocol(Protocol):
    def health(self) -> bool:
        ...

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model_name: str,
        max_seq_length: int,
        normalize: bool,
        dtype: str,
        show_progress: bool,
    ) -> np.ndarray:
        ...


def _default_embedder_factory(base_url: str) -> EmbedderProtocol:
    return HttpEmbedder(base_url)


@dataclass(frozen=True)
class RetrievalResult:
    score: float
    doc: Dict[str, Any]
    faiss_idx: int


class EmbedServerError(RuntimeError):
    def __init__(self, embed_url: str) -> None:
        super().__init__(f"embedding server unreachable at {embed_url}")
        self.embed_url = embed_url


@dataclass
class FaissRetriever:
    packet_dir: Path
    embed_url: Optional[str] = None
    embedder_factory: Optional[EmbedderFactory] = None
    manifest: Dict[str, Any] = field(init=False)
    docs: List[Dict[str, Any]] = field(init=False)
    index: faiss.Index = field(init=False)
    model_name: str = field(init=False)
    max_seq_length: int = field(init=False)

    def __post_init__(self) -> None:
        self.embed_url = self.embed_url or os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8876")
        self.embedder_factory = self.embedder_factory or _default_embedder_factory
        manifest_path = self.packet_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"missing manifest.json at {manifest_path}")
        manifest_text = manifest_path.read_text(encoding="utf-8")
        self.manifest = json.loads(manifest_text)
        embedding_cfg = self.manifest.get("embedding") or {}
        self.model_name = embedding_cfg["model"]
        self.max_seq_length = int(embedding_cfg.get("max_seq_length", 1024))
        self.docs = self._load_docs()
        self.index = self._load_index()

    def _load_docs(self) -> List[Dict[str, Any]]:
        docs_path = self.packet_dir / "docs.jsonl"
        if not docs_path.exists():
            raise FileNotFoundError(f"missing docs.jsonl at {docs_path}")
        docs: List[Dict[str, Any]] = []
        with docs_path.open("r", encoding="utf-8") as docs_file:
            for line in docs_file:
                docs.append(json.loads(line))
        return docs

    def _load_index(self) -> faiss.Index:
        index_path = self.packet_dir / "faiss" / "index.faiss"
        if not index_path.exists():
            raise FileNotFoundError(f"missing faiss index at {index_path}")
        return faiss.read_index(str(index_path))

    def _new_embedder(self) -> EmbedderProtocol:
        embedder = self.embedder_factory(self.embed_url)
        if not embedder.health():
            raise EmbedServerError(self.embed_url)
        return embedder

    def retrieve(self, query: str, k: int) -> List[RetrievalResult]:
        embedder = self._new_embedder()
        query_vec = embedder.embed_texts(
            [query],
            model_name=self.model_name,
            max_seq_length=self.max_seq_length,
            normalize=True,
            dtype="float32",
            show_progress=False,
        )
        scores, ids = self.index.search(query_vec, int(k))
        scores = scores[0]
        ids = ids[0]
        hits: List[RetrievalResult] = []
        for idx, score in zip(ids, scores):
            if int(idx) < 0:
                continue
            doc = self.docs[int(idx)]
            hits.append(RetrievalResult(score=float(score), doc=doc, faiss_idx=int(idx)))
        return hits


RetrieverFactory = Callable[[Path, Optional[str]], FaissRetriever]


def _default_retriever_factory(packet_dir: Path, embed_url: Optional[str]) -> FaissRetriever:
    return FaissRetriever(packet_dir=packet_dir, embed_url=embed_url)


@dataclass
class QueryCommand:
    cpm_dir: Path
    packet: str
    query: str
    k: int = 5
    metadata_filters: MetadataFilters = ()
    use_cache: bool = True
    cache_refresh: bool = False
    embed_url: Optional[str] = None
    retriever_factory: RetrieverFactory = field(default=_default_retriever_factory)

    def __post_init__(self) -> None:
        self.metadata_filters = tuple(self.metadata_filters)

    def execute(self) -> None:
        packet_dir = resolve_current_packet_dir(self.cpm_dir, self.packet)
        if packet_dir is None:
            tried = (self.cpm_dir / self.packet).resolve()
            print(f"[cpm:query] packet not found: {self.packet}")
            print(f"           tried: {tried}")
            return

        use_cache = bool(self.use_cache)
        refresh_cache = bool(self.cache_refresh)
        if not use_cache and refresh_cache:
            print("[cpm:query] warning: --no-cache overrides --cache-refresh")

        retriever = self.retriever_factory(packet_dir, self.embed_url)
        canon = _canonicalize_query_args(
            packet_dir=packet_dir,
            packet_arg=self.packet,
            cpm_dir=self.cpm_dir,
            query=self.query,
            k=self.k,
            model_name=retriever.model_name,
            max_seq_length=retriever.max_seq_length,
            metadata_filters=self.metadata_filters,
        )
        cache_key = _stable_sha256(canon)

        if use_cache and not refresh_cache:
            cached = _cache_load(packet_dir, cache_key)
            if cached is not None:
                payload = cached.get("payload") or {}
                cached_results = payload.get("results") or []
                _print_results("[cpm:query][cache-hit]", self.query, self.k, packet_dir.name, cached_results)
                return

        try:
            retrieved = retriever.retrieve(self.query, self.k)
        except EmbedServerError as err:
            print(f"[error] embedding server not reachable at {err.embed_url}")
            print("        - start it with: rag cpm embed start-server --detach")
            print("        - or set RAG_EMBED_URL")
            return

        filtered = [
            hit
            for hit in retrieved
            if _metadata_matches(hit.doc.get("metadata"), self.metadata_filters)
        ]
        records = _build_result_records(filtered)

        tag = "[cpm:query]"
        if refresh_cache:
            tag = "[cpm:query][cache-refresh]"
        elif not use_cache:
            tag = "[cpm:query][no-cache]"

        _print_results(tag, self.query, self.k, packet_dir.name, records)

        if use_cache:
            record = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "cache_key": f"sha256:{cache_key}",
                "command": {
                    "args_canonical": canon,
                    "metadata_filters": _record_metadata_filters(self.metadata_filters),
                },
                "environment": {
                    "packet_dir": str(packet_dir).replace("\\", "/"),
                },
                "payload": {
                    "results": records,
                    "query_vec": None,
                    "result_vecs": None,
                },
            }
            _cache_store(packet_dir, cache_key, record)


def _parse_metadata_filters(raw_filters: Sequence[str]) -> List[Tuple[str, str]]:
    parsed: List[Tuple[str, str]] = []
    for raw in raw_filters:
        if "=" not in raw:
            raise ValueError(f"metadata filter '{raw}' must be formatted as key=value")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"metadata filter '{raw}' must include non-empty key and value")
        parsed.append((key, value))
    return parsed


def _serialize_metadata_filters(filters: MetadataFilters) -> Tuple[str, ...]:
    return tuple(sorted(f"{key}={value}" for key, value in filters))


def _metadata_matches(
    metadata: Optional[Dict[str, Any]],
    filters: MetadataFilters,
) -> bool:
    if not filters:
        return True
    meta = metadata or {}
    for key, value in filters:
        if str(meta.get(key)) != value:
            return False
    return True


def _build_result_records(results: Sequence[RetrievalResult]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    rank = 0
    for hit in results:
        rank += 1
        records.append(
            {
                "rank": rank,
                "score": float(hit.score),
                "faiss_idx": hit.faiss_idx,
                "doc": hit.doc,
            }
        )
    return records


def _canonicalize_query_args(
    *,
    packet_dir: Path,
    packet_arg: str,
    cpm_dir: Path,
    query: str,
    k: int,
    model_name: str,
    max_seq_length: int,
    metadata_filters: MetadataFilters,
) -> Dict[str, Any]:
    return {
        "cmd": "cpm.query",
        "packet_arg": packet_arg,
        "packet_dir": str(packet_dir).replace("\\", "/"),
        "query": (query or "").strip(),
        "k": int(k),
        "cpm_dir": str(cpm_dir).replace("\\", "/"),
        "embedding_model": model_name,
        "max_seq_length": int(max_seq_length),
        "normalize": True,
        "metadata_filters": list(_serialize_metadata_filters(metadata_filters)),
        "schema_version": CACHE_SCHEMA_VERSION,
    }


def _stable_sha256(obj: Dict[str, Any]) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _history_dir(packet_dir: Path) -> Path:
    return packet_dir / ".history" / f"v{CACHE_SCHEMA_VERSION}"


def _cache_path(packet_dir: Path, cache_key: str) -> Path:
    return _history_dir(packet_dir) / f"{cache_key}.json"


def _cache_load(packet_dir: Path, cache_key: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(packet_dir, cache_key)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _cache_store(packet_dir: Path, cache_key: str, record: Dict[str, Any]) -> None:
    directory = _history_dir(packet_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = _cache_path(packet_dir, cache_key)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _record_metadata_filters(filters: MetadataFilters) -> List[Dict[str, str]]:
    return [{"key": key, "value": value} for key, value in filters]


def _print_results(header: str, query: str, k: int, packet_name: str, results: List[Dict[str, Any]]) -> None:
    print(f"{header} '{query}' (k={k}) packet={packet_name}")
    for r in results:
        rank = r.get("rank")
        sc = r.get("score")
        doc = r.get("doc") or {}
        meta = doc.get("metadata") or {}
        print(f"\n#{rank} score={float(sc):.4f} id={doc.get('id')}")
        if meta.get("path"):
            print(f"   path={meta['path']} lines={meta.get('line_start')}-{meta.get('line_end')}")
        print(doc.get("text", ""))


def cmd_query(args) -> None:
    try:
        filters = _parse_metadata_filters(getattr(args, "metadata", []) or [])
    except ValueError as err:
        print(f"[cpm:query] {err}")
        return

    command = QueryCommand(
        cpm_dir=Path(args.cpm_dir or ".cpm"),
        packet=args.packet,
        query=args.query,
        k=args.k,
        metadata_filters=filters,
        use_cache=not getattr(args, "no_cache", False),
        cache_refresh=getattr(args, "cache_refresh", False),
    )
    command.execute()
