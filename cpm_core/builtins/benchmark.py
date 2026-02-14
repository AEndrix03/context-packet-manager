"""Benchmark command for runtime KPI sampling."""

from __future__ import annotations

import json
import math
import statistics
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cpm_core.api import cpmcommand
from cpm_core.registry import CPMRegistryEntry

from .commands import _WorkspaceAwareCommand
from .query import (
    DEFAULT_INDEXER,
    DEFAULT_RERANKER,
    DEFAULT_RETRIEVER,
    QueryCommand,
)


@cpmcommand(name="benchmark", group="cpm")
class BenchmarkCommand(_WorkspaceAwareCommand):
    """Run repeated query executions and report latency/context KPI metrics."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument("--packet", required=True, help="Packet name or path")
        parser.add_argument("--query", required=True, help="Query text")
        parser.add_argument("--runs", type=int, default=3, help="Number of benchmark runs")
        parser.add_argument("-k", type=int, default=5, help="Top-k retrieval")
        parser.add_argument("--indexer", default=DEFAULT_INDEXER, help="Indexer strategy")
        parser.add_argument("--reranker", default=DEFAULT_RERANKER, help="Reranker strategy")
        parser.add_argument("--queries-file", help="JSON file with query list for IR evaluation")
        parser.add_argument("--qrels-file", help="JSON file with relevance judgements")
        parser.add_argument("--out", help="Write benchmark report JSON to this path")
        parser.add_argument("--max-latency-ms", type=float, help="Fail if avg latency exceeds threshold")
        parser.add_argument("--min-citation-coverage", type=float, help="Fail if citation coverage is below threshold")
        parser.add_argument("--min-ndcg", type=float, help="Fail if IR nDCG@k is below threshold")
        parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    def run(self, argv: Any) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        query_command = QueryCommand()
        query_command.workspace_root = workspace_root
        entry = query_command._resolve_retriever_entry(  # noqa: SLF001
            query_command._load_retriever_entries(workspace_root),  # noqa: SLF001
            DEFAULT_RETRIEVER,
        )
        if entry is None:
            print("[cpm:benchmark] native retriever not available")
            return 1

        run_count = max(int(getattr(argv, "runs", 3)), 1)
        durations_ms: list[float] = []
        tokens: list[int] = []
        citations_ratio: list[float] = []
        ok_runs = 0
        first_payload: dict[str, Any] | None = None
        for _ in range(run_count):
            started = time.perf_counter()
            payload = query_command._invoke_retriever(  # noqa: SLF001
                entry=entry,
                packet=str(argv.packet),
                query=str(argv.query),
                k=int(argv.k),
                cpm_dir=workspace_root,
                embed_url=None,
                embed_mode=None,
                indexer=str(argv.indexer),
                reranker=str(argv.reranker),
                selected_model=None,
                max_context_tokens=6000,
            )
            durations_ms.append((time.perf_counter() - started) * 1000.0)
            if payload.get("ok", True):
                ok_runs += 1
            compiled = payload.get("compiled_context") if isinstance(payload.get("compiled_context"), dict) else {}
            tokens.append(int(compiled.get("token_estimate") or 0))
            snippets = compiled.get("core_snippets") if isinstance(compiled.get("core_snippets"), list) else []
            cited = [item for item in snippets if isinstance(item, dict) and str(item.get("citation") or "").strip()]
            if snippets:
                citations_ratio.append(len(cited) / len(snippets))
            if first_payload is None:
                first_payload = payload

        report = {
            "ok": True,
            "runs": run_count,
            "success_rate": round(ok_runs / run_count, 4),
            "latency_ms_avg": round(statistics.mean(durations_ms), 3),
            "latency_ms_p95": round(_p95(durations_ms), 3),
            "token_avg": round(statistics.mean(tokens), 2) if tokens else 0.0,
            "citation_coverage_avg": round(statistics.mean(citations_ratio), 4) if citations_ratio else 0.0,
            "result_count": len(first_payload.get("results", [])) if isinstance(first_payload, dict) else 0,
            "indexer": str(argv.indexer),
            "reranker": str(argv.reranker),
            "packet": str(argv.packet),
            "query": str(argv.query),
        }
        queries_file = str(getattr(argv, "queries_file", "") or "").strip()
        qrels_file = str(getattr(argv, "qrels_file", "") or "").strip()
        if queries_file and qrels_file:
            report["ir_metrics"] = _evaluate_ir_metrics(
                config=IrBenchmarkConfig(
                    workspace_root=workspace_root,
                    packet=str(argv.packet),
                    indexer=str(argv.indexer),
                    reranker=str(argv.reranker),
                    k=int(argv.k),
                    queries_path=Path(queries_file),
                    qrels_path=Path(qrels_file),
                ),
                entry=entry,
            )
        report["kpi_gates"] = _evaluate_gates(
            report=report,
            max_latency_ms=getattr(argv, "max_latency_ms", None),
            min_citation_coverage=getattr(argv, "min_citation_coverage", None),
            min_ndcg=getattr(argv, "min_ndcg", None),
        )
        _write_benchmark_report(
            workspace_root=workspace_root,
            report=report,
            explicit_out=str(getattr(argv, "out", "") or "").strip() or None,
        )

        if str(getattr(argv, "format", "text")) == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if bool(report["kpi_gates"]["ok"]) else 1

        print(f"[cpm:benchmark] runs={report['runs']} success_rate={report['success_rate']}")
        print(
            f"[cpm:benchmark] latency_avg_ms={report['latency_ms_avg']} "
            f"latency_p95_ms={report['latency_ms_p95']}"
        )
        print(
            f"[cpm:benchmark] token_avg={report['token_avg']} "
            f"citation_coverage_avg={report['citation_coverage_avg']}"
        )
        print(
            f"[cpm:benchmark] packet={report['packet']} query={report['query']} "
            f"indexer={report['indexer']} reranker={report['reranker']}"
        )
        ir_metrics = report.get("ir_metrics")
        if isinstance(ir_metrics, dict):
            print(
                f"[cpm:benchmark] ir mrr={ir_metrics.get('mrr')} "
                f"ndcg@k={ir_metrics.get('ndcg_at_k')} recall@k={ir_metrics.get('recall_at_k')}"
            )
        gates = report.get("kpi_gates")
        if isinstance(gates, dict) and not bool(gates.get("ok", True)):
            print(f"[cpm:benchmark] gate_failed={','.join(gates.get('failures', []))}")
            return 1
        return 0


@dataclass(frozen=True)
class IrBenchmarkConfig:
    workspace_root: Path
    packet: str
    indexer: str
    reranker: str
    k: int
    queries_path: Path
    qrels_path: Path


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round(0.95 * (len(ordered) - 1)))
    return float(ordered[index])


def _ndcg(ranked_gains: list[float], ideal_gains: list[float], k: int) -> float:
    limit = max(k, 1)
    dcg = 0.0
    for index, gain in enumerate(ranked_gains[:limit], start=1):
        dcg += gain / math.log2(index + 1.0)
    idcg = 0.0
    for index, gain in enumerate(ideal_gains[:limit], start=1):
        idcg += gain / math.log2(index + 1.0)
    if idcg <= 0:
        return 0.0
    return dcg / idcg


def _evaluate_ir_metrics(*, config: IrBenchmarkConfig, entry: CPMRegistryEntry) -> dict[str, Any]:
    try:
        queries_payload = json.loads(config.queries_path.read_text(encoding="utf-8"))
        qrels_payload = json.loads(config.qrels_path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "invalid_ir_input"}
    if not isinstance(queries_payload, list) or not isinstance(qrels_payload, dict):
        return {"ok": False, "error": "invalid_ir_input"}
    query_command = QueryCommand()
    query_command.workspace_root = config.workspace_root

    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    recalls: list[float] = []
    evaluated = 0
    for item in queries_payload:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not qid or not text:
            continue
        relevance = qrels_payload.get(qid)
        if not isinstance(relevance, dict):
            continue
        ranked = query_command._invoke_retriever(  # noqa: SLF001
            entry=entry,
            packet=config.packet,
            query=text,
            k=config.k,
            cpm_dir=config.workspace_root,
            embed_url=None,
            embed_mode=None,
            indexer=config.indexer,
            reranker=config.reranker,
            selected_model=None,
            max_context_tokens=6000,
        )
        results = ranked.get("results") if isinstance(ranked.get("results"), list) else []
        scores = []
        rank_of_first_rel = 0
        relevant_retrieved = 0
        for rank, hit in enumerate(results[: max(config.k, 1)], start=1):
            if not isinstance(hit, dict):
                scores.append(0.0)
                continue
            doc_id = str(hit.get("id") or "")
            gain = float(relevance.get(doc_id, 0.0))
            scores.append(gain)
            if gain > 0 and rank_of_first_rel == 0:
                rank_of_first_rel = rank
            if gain > 0:
                relevant_retrieved += 1
        reciprocal_ranks.append(1.0 / rank_of_first_rel if rank_of_first_rel else 0.0)
        ndcgs.append(_ndcg(scores, sorted((float(v) for v in relevance.values()), reverse=True), config.k))
        total_relevant = len([value for value in relevance.values() if float(value) > 0.0])
        recalls.append((relevant_retrieved / total_relevant) if total_relevant else 0.0)
        evaluated += 1

    if evaluated == 0:
        return {"ok": False, "error": "no_ir_samples"}
    return {
        "ok": True,
        "samples": evaluated,
        "mrr": round(statistics.mean(reciprocal_ranks), 6),
        "ndcg_at_k": round(statistics.mean(ndcgs), 6),
        "recall_at_k": round(statistics.mean(recalls), 6),
    }


def _evaluate_gates(
    *,
    report: dict[str, Any],
    max_latency_ms: float | None,
    min_citation_coverage: float | None,
    min_ndcg: float | None,
) -> dict[str, Any]:
    failures: list[str] = []
    latency_avg = float(report.get("latency_ms_avg") or 0.0)
    citation = float(report.get("citation_coverage_avg") or 0.0)
    if max_latency_ms is not None and latency_avg > float(max_latency_ms):
        failures.append("latency")
    if min_citation_coverage is not None and citation < float(min_citation_coverage):
        failures.append("citation_coverage")
    ir = report.get("ir_metrics") if isinstance(report.get("ir_metrics"), dict) else None
    if min_ndcg is not None:
        ndcg = float(ir.get("ndcg_at_k") or 0.0) if isinstance(ir, dict) else 0.0
        if ndcg < float(min_ndcg):
            failures.append("ndcg")
    return {"ok": len(failures) == 0, "failures": failures}


def _write_benchmark_report(*, workspace_root: Path, report: dict[str, Any], explicit_out: str | None) -> Path:
    if explicit_out:
        path = Path(explicit_out)
    else:
        root = workspace_root / "state" / "benchmarks"
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        path = root / f"benchmark-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
