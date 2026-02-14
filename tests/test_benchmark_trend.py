from __future__ import annotations

import json
from pathlib import Path

import pytest

from cpm_cli.main import main as cli_main

EXPECTED_LATENCY_DELTA = 10.0
EXPECTED_CITATION_DELTA = -0.1


def test_benchmark_trend_outputs_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))
    bench_root = workspace_root / "state" / "benchmarks"
    bench_root.mkdir(parents=True, exist_ok=True)
    (bench_root / "benchmark-20260101T000000Z.json").write_text(
        json.dumps(
            {
                "latency_ms_avg": 100.0,
                "latency_ms_p95": 120.0,
                "citation_coverage_avg": 1.0,
                "token_avg": 500.0,
            }
        ),
        encoding="utf-8",
    )
    (bench_root / "benchmark-20260102T000000Z.json").write_text(
        json.dumps(
            {
                "latency_ms_avg": 110.0,
                "latency_ms_p95": 150.0,
                "citation_coverage_avg": 0.9,
                "token_avg": 550.0,
            }
        ),
        encoding="utf-8",
    )

    code = cli_main(
        [
            "benchmark-trend",
            "--workspace-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
        start_dir=tmp_path,
    )
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    metrics = payload["metrics"]
    assert metrics["latency_ms_avg"]["delta"] == EXPECTED_LATENCY_DELTA
    assert metrics["citation_coverage_avg"]["delta"] == EXPECTED_CITATION_DELTA


def test_benchmark_trend_custom_metric_and_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = tmp_path / ".cpm"
    monkeypatch.setenv("RAG_CPM_DIR", str(workspace_root))
    bench_root = workspace_root / "state" / "benchmarks"
    bench_root.mkdir(parents=True, exist_ok=True)
    for index in range(3):
        (bench_root / f"benchmark-2026010{index+1}T000000Z.json").write_text(
            json.dumps({"latency_ms_avg": float(100 + index)}),
            encoding="utf-8",
        )

    code = cli_main(
        [
            "benchmark-trend",
            "--workspace-dir",
            str(tmp_path),
            "--limit",
            "2",
            "--metric",
            "latency_ms_avg",
        ],
        start_dir=tmp_path,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "metric=latency_ms_avg" in out
