# MCP Tools (Remote-First)

This section documents MCP tooling exposed by `cpm mcp:serve`.

## Overview

- `lookup`: remote-first metadata lookup (OCI manifest + metadata blob), returns digest-pinned ref.
- `query`: cache-first query; on miss it lazy-materializes from OCI and reuses local cache.
- `plan_from_intent`: deterministic planner that emits `intent_mode` (`lookup` vs `query`) plus executable templates.
- `evidence_digest`: compressed evidence snippets + short technical digest.

## Read Next

- `docs/mcp/quickstart.md` — start server and connect Claude Desktop / Claude Code / Codex / VS Code
- `docs/mcp/config.md`
- `docs/mcp/tools/lookup.md`
- `docs/mcp/tools/query.md`
- `docs/mcp/tools/plan_from_intent.md`
- `docs/mcp/tools/evidence_digest.md`
- `docs/mcp/recipes/llm-integration.md`
