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
