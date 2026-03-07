# CPM MCP Plugin

MCP plugin that exposes CPM packet tooling through a FastMCP server.

## Tools

- `lookup`: remote-first metadata lookup, returns digest-pinned packet refs.
- `query`: local-hit / remote-miss lazy query over OCI packets.
- `plan_from_intent`: deterministic metadata-first planner.
- `evidence_digest`: compressed snippets + short technical digest.

## Configuration

Primary environment variables:

- `REGISTRY`
- `CPM_ROOT` (default `.cpm`)
- `EMBEDDING_URL`
- `EMBEDDING_MODEL`

Compatibility fallbacks:

- `RAG_CPM_DIR`
- `RAG_EMBED_URL`
- `RAG_EMBED_MODE`

Resolver OCI options (from `CPM_ROOT/config/config.toml`, `[oci]` section):

- `timeout_seconds` and `max_retries` for fail-fast lookup/query behavior
- `insecure` for insecure TLS
- `plain_http` for HTTP-only local registries

Lookup diagnostics are appended to `CPM_ROOT/logs/mcp-lookup.log`.

## Start

```powershell
cpm mcp:serve
```

Optional process-local overrides:

```powershell
cpm mcp:serve --registry registry.local/project --cpm-dir .cpm --embed-url http://127.0.0.1:8876 --embed-model mixedbread-ai/mxbai-embed-large-v1
```

## Recommended runtime flow

1. `lookup(name=..., alias="latest")`
2. use `selected.pinned_uri`
3. `query(ref=<pinned_uri>, q=<question>)`

## Internals

- env contract: `cpm_mcp_plugin/env.py`
- remote wrappers: `cpm_mcp_plugin/remote.py`
- MCP registration: `cpm_mcp_plugin/server.py`
