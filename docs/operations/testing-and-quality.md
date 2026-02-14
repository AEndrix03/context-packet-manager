# Testing And Quality

## Stack quality
- formatter: `black` (line-length 120)
- lint: `ruff`
- typing: `mypy`
- test runner: `pytest`

## Strategia test
La suite copre CLI dispatch, build/query flow, embeddings, plugin discovery, OCI publish/install, registry client.

## Esecuzione locale
```powershell
python -m pytest -q
python -m ruff check .
python -m mypy cpm_core cpm_cli cpm_builtin cpm_plugins
```

## Regole
- ogni fix deve includere test di regressione quando applicabile,
- preferire test mirati durante sviluppo, suite completa prima di merge.

## Supply-chain runtime checks
- `cpm query --as-of ...` deve avere test snapshot lock storico.
- `cpm replay <log>` deve verificare hash output deterministico.
- `cpm diff left right --max-drift <x>` deve restituire exit code non-zero se supera soglia.
- `cpm benchmark --runs N` misura KPI runtime (latenza, token medi, citation coverage).
- `cpm benchmark --queries-file queries.json --qrels-file qrels.json` misura KPI IR (`MRR`, `nDCG@k`, `recall@k`).
- KPI gate CI disponibili: `--max-latency-ms`, `--min-citation-coverage`, `--min-ndcg` (exit code 1 se violati).
- Confronto baseline: `--baseline report.json` + gate delta (`--max-latency-regression-pct`, `--min-ndcg-delta`, `--min-mrr-delta`).
