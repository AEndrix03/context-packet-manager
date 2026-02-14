"""Benchmark trend analysis command."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from statistics import mean
from typing import Any

from cpm_core.api import cpmcommand

from .commands import _WorkspaceAwareCommand

DEFAULT_METRICS = (
    "latency_ms_avg",
    "latency_ms_p95",
    "citation_coverage_avg",
    "token_avg",
)


@cpmcommand(name="benchmark-trend", group="cpm")
class BenchmarkTrendCommand(_WorkspaceAwareCommand):
    """Summarize historical benchmark reports and KPI trends."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument("--limit", type=int, default=20, help="Max number of reports to include")
        parser.add_argument(
            "--metric",
            action="append",
            help="Metric key to include (repeatable). Defaults to common runtime KPIs.",
        )
        parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    def run(self, argv: Any) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        trend_root = workspace_root / "state" / "benchmarks"
        if not trend_root.exists():
            print(f"[cpm:benchmark-trend] no benchmark history at {trend_root}")
            return 1

        files = sorted(path for path in trend_root.glob("benchmark-*.json") if path.is_file())
        if not files:
            print(f"[cpm:benchmark-trend] no benchmark reports found at {trend_root}")
            return 1
        limit = max(int(getattr(argv, "limit", 20)), 1)
        selected = files[-limit:]
        reports = []
        for path in selected:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                payload["_path"] = str(path)
                reports.append(payload)
        if not reports:
            print("[cpm:benchmark-trend] no valid benchmark reports")
            return 1

        requested_metrics = getattr(argv, "metric", None)
        metrics = (
            tuple(str(item).strip() for item in requested_metrics if str(item).strip())
            if requested_metrics
            else DEFAULT_METRICS
        )
        summary = _summarize_trend(reports=reports, metrics=metrics)
        response = {
            "ok": True,
            "reports": len(reports),
            "first_report": reports[0].get("_path"),
            "last_report": reports[-1].get("_path"),
            "metrics": summary,
        }

        if str(getattr(argv, "format", "text")) == "json":
            print(json.dumps(response, indent=2, ensure_ascii=False))
            return 0

        print(
            f"[cpm:benchmark-trend] reports={response['reports']} "
            f"first={response['first_report']} last={response['last_report']}"
        )
        for key, value in summary.items():
            print(
                f"[cpm:benchmark-trend] metric={key} avg={value['avg']} min={value['min']} "
                f"max={value['max']} delta={value['delta']}"
            )
        return 0


def _summarize_trend(*, reports: list[dict[str, Any]], metrics: tuple[str, ...]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for metric in metrics:
        values = [float(item.get(metric)) for item in reports if isinstance(item.get(metric), (int, float))]
        if not values:
            continue
        summary[metric] = {
            "avg": round(mean(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "delta": round(values[-1] - values[0], 6),
        }
    return summary
