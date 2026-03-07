# MCP Configuration

MCP runtime is configured with environment variables.

## Required (Remote Flows)

- `REGISTRY`: OCI base repository for non-fully-qualified refs.
- `CPM_ROOT`: local cache/workspace root (default: `.cpm`).
- `EMBEDDING_URL`: embedding HTTP endpoint used by query.
- `EMBEDDING_MODEL`: query-time embedding model.

## Compatibility Variables

- `RAG_CPM_DIR` is accepted as fallback for `CPM_ROOT`.
- `RAG_EMBED_URL` is accepted as fallback for `EMBEDDING_URL`.
- `RAG_EMBED_MODE` defaults to `http` if not set.

## Precedence

- Tool arguments override env values.
- Env values override defaults.
- Only `CPM_ROOT` has a built-in default (`.cpm`).

## Cache Layout (`CPM_ROOT`)

- `cache/metadata/*.json`: resolver metadata cache by digest.
- `cache/metadata_alias/*.json`: short TTL alias cache (`latest`, etc.).
- `cas/<digest>/payload/`: lazy materialized packet payload.
- `index/<digest>/<embedding_fingerprint>/`: index cache.
- `meta/<digest>/packet.manifest.json`: normalized metadata copy.
- `logs/mcp-lookup.log`: lookup attempt diagnostics (attempt/failure/success).

## OCI Runtime Tuning (`CPM_ROOT/config/config.toml`)

`lookup/query` resolver reads optional `[oci]` settings:

- `timeout_seconds` (default `10.0` in resolver path)
- `max_retries` (default `1` in resolver path)
- `backoff_seconds` (default `0.2`)
- `insecure` (append `--insecure` to ORAS commands)
- `plain_http` (append `--plain-http` to ORAS commands)
