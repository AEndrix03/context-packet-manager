"""Benchmark command for runtime KPI sampling."""

from __future__ import annotations

import json
import statistics
import time
from argparse import ArgumentParser
from typing import Any

from cpm_core.api import cpmcommand

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

        if str(getattr(argv, "format", "text")) == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0

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
        return 0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round(0.95 * (len(ordered) - 1)))
    return float(ordered[index])
