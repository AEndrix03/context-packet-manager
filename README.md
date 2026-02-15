# CPM - Context Packet Manager

Transform docs and code into trusted, queryable context for LLM workflows.

## Why CPM

- Fast local runtime (`build`, `query`, `replay`, `diff`, `benchmark`)
- Trust-aware context supply chain (signature, SBOM, provenance, trust score)
- Hybrid retrieval + structured context compilation
- OCI distribution for reproducible install/query across environments

## Quick Start

```bash
git clone https://github.com/AEndrix03/component-rag.git
cd component-rag
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .

cpm init
cpm doctor

cpm embed add \
  --name local-adapter \
  --url http://127.0.0.1:8080 \
  --model text-embedding-3-small \
  --dims 768 \
  --set-default

cpm build --source ./docs --name my-docs --version 1.0.0
cpm query --packet my-docs --query "authentication setup" -k 5
```

## Lazy Query From Registry (No Manual Install)

```bash
# Direct OCI source
cpm query \
  --query "authentication setup" \
  --registry oci://registry.local/project/my-docs@1.0.0 \
  --embed text-embedding-3-small

# OCI repository base + packet
cpm query \
  --packet my-docs@1.0.0 \
  --query "authentication setup" \
  --registry registry.local/project

# Hub/HTTP resolver source
cpm query \
  --query "authentication setup" \
  --registry "http://127.0.0.1:8786/v1/resolve?source=oci://registry.local/project/my-docs@1.0.0"
```

Notes:
- `--registry` is a lazy source shortcut (`oci://`, `http(s)://`, `dir://`, or OCI repository base).
- `--embed` overrides query-time embedding model.
- If `--embed` is omitted in lazy mode, CPM defaults to `text-embedding-3-small`.

## Common Commands

```bash
# Hybrid query
cpm query --packet my-docs --query "auth" --indexer hybrid-rrf --max-context-tokens 4000

# Time-travel + replay
cpm query --packet my-docs --query "auth" --as-of 2025-06-01
cpm replay ./.cpm/state/replay/query-20260101T120000Z.json

# Drift and benchmark
cpm diff my-docs@1.0.0 my-docs@1.1.0 --max-drift 0.05
cpm benchmark --packet my-docs --query "auth" --runs 5 --format json
cpm benchmark-trend --format json
```

## OCI Publish/Install

```bash
cpm publish --from-dir ./dist/demo/1.0.0 --registry registry.local/project
cpm install demo@1.0.0 --registry registry.local/project
cpm query --packet demo --query "authentication setup"
```

## Policy and Hub

`.cpm/policy.yml`:

```yaml
policy:
  mode: strict
  allowed_sources:
    - oci://registry.local/*
  min_trust_score: 0.8
  max_tokens: 6000
```

Optional remote policy evaluation (`.cpm/config/config.toml`):

```toml
[hub]
url = "http://127.0.0.1:8786"
enforce_remote_policy = true
```

## Documentation

Start here:
- `docs/get-started.md`
- `docs/README.md`
- `DOCUMENTATION.md`

Deep dives:
- `docs/flows/query-flow.md`
- `docs/components/oci-publish-install.md`
- `docs/operations/workspace-and-config.md`
- `docs/operations/testing-and-quality.md`

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m mypy cpm_core cpm_cli cpm_builtin cpm_plugins
```

License: GPL-3.0 (`LICENSE`).
