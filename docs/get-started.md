# Get Started In Minutes

Goal: clone CPM and run your first query quickly.

## 1) Clone and install

```bash
git clone https://github.com/AEndrix03/component-rag.git
cd component-rag
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

## 2) Initialize workspace

```bash
cpm init
cpm doctor
```

This creates `.cpm/` with config, state and package folders.

## 3) Add one embeddings provider

CPM expects an OpenAI-compatible embeddings endpoint (`POST /v1/embeddings`).

```bash
cpm embed add \
  --name local-adapter \
  --url http://127.0.0.1:8080 \
  --model text-embedding-3-small \
  --dims 768 \
  --set-default
```

## 4) Build and query

```bash
cpm build --source ./docs --name my-docs --version 1.0.0
cpm query --packet my-docs --query "authentication setup" -k 5
```

## 5) Next commands

```bash
# Hybrid retrieval
cpm query --packet my-docs --query "auth" --indexer hybrid-rrf

# OCI distribution
cpm publish --from-dir ./dist/my-docs/1.0.0 --registry registry.local/project
cpm install my-docs@1.0.0 --registry registry.local/project

# Repro/audit
cpm replay ./.cpm/state/replay/query-*.json
cpm diff my-docs@1.0.0 my-docs@1.1.0
cpm benchmark --packet my-docs --query "auth" --runs 5
```

## Troubleshooting

- If `query` fails with embedding errors: check provider URL/model in `.cpm/config/embeddings.yml`.
- If packet is not found: run `cpm lookup` and verify packet/version.
- If OCI policy fails: check `.cpm/policy.yml` and optional `[hub]` settings in `.cpm/config/config.toml`.

## Where to go next

- Query internals: `docs/flows/query-flow.md`
- Build internals: `docs/flows/build-flow.md`
- Runtime policy and workspace: `docs/operations/workspace-and-config.md`
- CI/quality/benchmarks: `docs/operations/testing-and-quality.md`
