# Codebase Structure
- `cpm/`: Core Context Packet Manager package, CLI, and chunkers. Source in `cpm/src/`.
- `embedding_pool/`: Embedding Pool server and runtime. Source in `embedding_pool/src/`.
- `registry/`: CPM Registry service and storage. Source in `registry/src/`.
- `.cpm/`: Local runtime configuration/cache created by `cpm init`.
- `.venv/`: Local virtual environment (not tracked).

Primary entrypoints:
- CPM CLI: `cpm` (core commands like build/query/publish)
- Embedding server: `cpm embed start-server`
- Registry server: `cpm-registry start`
- MCP server: `cpm mcp serve`