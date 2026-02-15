# CPM

CPM (Context Packet Manager) turns docs and code into trusted, queryable context packets for LLM workflows.

Why teams use it:
- Fast local runtime (`build`, `query`, `diff`, `replay`, `benchmark`)
- Supply-chain checks for context (`signature`, `SBOM`, `provenance`, trust score)
- Plugin-based architecture (commands/builders/retrievers)
- OCI publish/install support for reproducible distribution

## Clone And Use Immediately

### 1) Install
```bash
git clone https://github.com/AEndrix03/component-rag.git
cd component-rag
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 2) Initialize workspace
```bash
cpm init
cpm doctor
```

### 3) Configure one embedding provider (OpenAI-compatible endpoint)
```bash
cpm embed add \
  --name local-adapter \
  --url http://127.0.0.1:8080 \
  --model text-embedding-3-small \
  --dims 768 \
  --set-default
```

### 4) Build and query your first packet
```bash
cpm build --source ./docs --name my-docs --version 1.0.0
cpm query --packet my-docs --query "authentication setup" -k 5
```

You now have a working local context runtime in `.cpm/`.

## Core Commands

```bash
# Build/query
cpm build --source ./docs --name my-docs --version 1.0.0
cpm query --packet my-docs --query "auth"

# Hybrid retrieval + context compiler
cpm query --packet my-docs --query "auth" --indexer hybrid-rrf --max-context-tokens 4000

# Time-travel and replay
cpm query --packet my-docs --query "auth" --as-of 2025-06-01
cpm replay ./.cpm/state/replay/query-20260101T120000Z.json

# Semantic diff / drift
cpm diff my-docs@1.0.0 my-docs@1.1.0 --max-drift 0.05

# Runtime KPI benchmarks
cpm benchmark --packet my-docs --query "auth" --runs 5 --format json
cpm benchmark --packet my-docs --query "auth" --queries-file ./bench/queries.json --qrels-file ./bench/qrels.json --format json
cpm benchmark --packet my-docs --query "auth" --max-latency-ms 200 --min-citation-coverage 1.0 --min-ndcg 0.70
cpm benchmark --packet my-docs --query "auth" --baseline ./bench/baseline.json --max-latency-regression-pct 15 --min-ndcg-delta -0.02 --min-mrr-delta -0.02
cpm benchmark-trend --format json
```

## OCI Workflow

```bash
# Publish a built packet
cpm publish --from-dir ./dist/demo/1.0.0 --registry registry.local/project

# Install packet from OCI
cpm install demo@1.0.0 --registry registry.local/project

# Query installed packet
cpm query --packet demo --query "authentication setup"
```

CPM install/query on OCI sources can enforce strict trust checks (signature/SBOM/provenance) and policy thresholds.

## Policy And Governance

Create `.cpm/policy.yml`:

```yaml
policy:
  mode: strict
  allowed_sources:
    - oci://registry.local/*
  min_trust_score: 0.8
  max_tokens: 6000
```

Optional Hub integration in `.cpm/config/config.toml`:

```toml
[hub]
url = "http://127.0.0.1:8786"
enforce_remote_policy = true
```

When configured, CPM evaluates policy locally and remotely (`/v1/policy/evaluate`).

## Documentation

Start here:
- `docs/README.md`: navigation by goal (setup, architecture, operations, contributing)
- `docs/get-started.md`: quick onboarding path (clone -> first query)

Deep dives:
- `docs/architecture/system-overview.md`
- `docs/flows/build-flow.md`
- `docs/flows/query-flow.md`
- `docs/components/oci-publish-install.md`
- `docs/operations/workspace-and-config.md`
- `docs/operations/testing-and-quality.md`

Project-wide indexes:
- `DOCUMENTATION.md`
- `cpm_core/README.md`
- `cpm_cli/README.md`

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m mypy cpm_core cpm_cli cpm_builtin cpm_plugins
```

License: `GPL-3.0` (see `LICENSE`).
