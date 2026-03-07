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
# Lazy query directly from registry
cpm query --query "auth setup" --registry oci://registry.local/project/my-docs@1.0.0

# Hybrid retrieval
cpm query --packet my-docs --query "auth" --indexer hybrid-rrf

# OCI distribution
cpm publish --from-dir ./dist/my-docs/1.0.0 --registry registry.local/project
cpm publish --from-dir ./my-docs --registry registry.local/project
cpm install my-docs@1.0.0 --registry registry.local/project

# Repro/audit
cpm replay ./.cpm/state/replay/query-*.json
cpm diff my-docs@1.0.0 my-docs@1.1.0
cpm benchmark --packet my-docs --query "auth" --runs 5
```

## Troubleshooting

- If `query` fails with embedding errors: check provider URL/model in `.cpm/config/embeddings.yml`.
- For lazy registry query, set `--embed <model>` to force model selection (default: `text-embedding-3-small`).
- If packet is not found: run `cpm lookup` and verify packet/version.
- For `publish`, if `--from-dir` is a packet name, CPM resolves `./dist/<name>/<version>` only when one version exists.
- `query/install/publish` registries are OCI-only (`oci://...` or `<registry>/<repo>`).
- If OCI policy fails: check `.cpm/policy.yml` and optional `[hub]` settings in `.cpm/config/config.toml`.
- If OCI query/publish fails with `basic credential not found`: your registry requires auth (`docker login <registry-host>`) or set `[oci].username/password` in `.cpm/config/config.toml`.
- For local dev registries without attestations, relax OCI verification in `.cpm/config/config.toml` with `[oci] strict_verify = false` (optionally also disable `require_signature/sbom/provenance`).
- If MCP lookup times out against local registries, set `[oci] plain_http = true` when registry serves HTTP and prefer `REGISTRY=host.docker.internal:<port>` if MCP runs in an isolated runtime.

## Where to go next

- Query internals: `docs/flows/query-flow.md`
- Build internals: `docs/flows/build-flow.md`
- Runtime policy and workspace: `docs/operations/workspace-and-config.md`
- CI/quality/benchmarks: `docs/operations/testing-and-quality.md`
