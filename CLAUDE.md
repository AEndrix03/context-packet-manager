# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CPM (Context Packet Manager) vNext — a modular Python framework for building, managing, and querying context packets for RAG applications. Transforms documentation and codebases into chunked, embedded, FAISS-indexed knowledge bases.

## Build & Development Commands

```bash
python -m venv .venv
pip install -e .            # editable install (all cpm_* packages)
pip install -e ".[dev]"     # includes black, ruff, mypy, pytest
```

```bash
pytest                      # run all tests (from repo root)
pytest tests/test_core.py   # run a single test file
pytest -k "test_name"       # run a specific test by name
black .                     # format (line-length 120)
ruff check .                # lint
mypy .                      # type check (--namespace-packages for pre-commit)
```

Pre-commit hooks run black, ruff, and mypy automatically.

## Architecture

The codebase is split into four top-level Python packages. All new development happens here — the `cpm/`, `embedding_pool/`, and `registry/` directories are legacy references only.

### cpm_core/ — Foundation layer
- **app.py** — `CPMApp` bootstraps all services (workspace, config, events, plugins, registry). Entry point for the runtime.
- **workspace.py** — `Workspace`, `WorkspaceLayout` (defines `.cpm/` directory structure), `WorkspaceResolver` (layered config: CLI > env > workspace > user > defaults).
- **services.py** — `ServiceContainer` lightweight DI with lazy singleton initialization.
- **registry/registry.py** — `FeatureRegistry` stores commands/builders/retrievers by qualified name (`group:name`). Handles disambiguation when simple names collide.
- **plugin/manager.py** — `PluginManager` discovers plugins from workspace and user directories, loads `plugin.toml` manifests, and runs lifecycle (discover → validate → init → register).
- **events.py** — `EventBus` with priority-based subscribe/emit for plugin lifecycle hooks.
- **api/abc.py** — Abstract base classes: `CPMAbstractCommand`, `CPMAbstractBuilder`, `CPMAbstractRetriever`.
- **compat.py** — Legacy command aliases. Tokens like `lookup`, `query`, `publish`, `install` are routed to the old CLI parser in `cpm/src/cli/`.
- **builtins/commands.py** — Core commands: `init`, `help`, `plugin:list`, `plugin:doctor`.

### cpm_cli/ — CLI routing
- **main.py** — `main()` bootstraps `CPMApp`, resolves command tokens against `FeatureRegistry`, delegates legacy tokens via `cpm_core.compat`.
- **cli.py** — Bridge for legacy `embed` subcommands.
- Entry point: `cpm = "cpm_cli.__main__:main"`.

### cpm_builtin/ — Built-in features
- **chunking/** — Language-aware chunkers: `python_ast`, `java`, `markdown`, `text`, `treesitter_generic`, `brace_fallback`. `router.py` selects the right chunker by file extension.
- **embeddings/** — `EmbeddingProviderConfig` (YAML), HTTP connector, caching.
- **packages/** — `PackageManager`, version parsing, directory layout helpers.
- **build.py**, **query.py**, **pkg.py** — Build, query, and package commands.

### cpm_plugins/ — Plugin implementations
- **mcp/** — Model Context Protocol plugin. Exposes `lookup` and `query` as FastMCP tools for Claude Desktop integration (stdio mode). Registered via `plugin.toml` manifest.

## Key Patterns

- **Feature registration**: All commands/builders/retrievers register in `FeatureRegistry` with `group:name` keys (e.g., `cpm:init`, `plugin:doctor`). Resolution tries simple name first, falls back to qualified name on collision.
- **Plugin lifecycle**: Plugins discovered via `plugin.toml` → entrypoint loaded → `PluginContext` passed → features registered in the shared registry.
- **Workspace layout**: `.cpm/packages/`, `.cpm/config/`, `.cpm/cache/`, `.cpm/plugins/`, `.cpm/state/`, `.cpm/logs/`. Config is TOML-based; embeddings config is YAML.
- **Legacy compatibility**: `cpm_core.compat` maps old CLI tokens to the legacy parser. `cpm doctor` prints the alias table and detects legacy `.cpm/` layouts needing migration.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `RAG_CPM_DIR` | `.cpm` | Workspace root |
| `RAG_EMBED_URL` | `http://127.0.0.1:8876` | Embedding server URL |
| `CPM_CONFIG` | `.cpm/config.yml` | Config file path |
| `CPM_EMBEDDINGS` | `.cpm/embeddings.yml` | Embeddings config path |

## Code Style

- Python >=3.11, type hints required (mypy enforced).
- Black formatting, line-length 120.
- Ruff linting: rules E, F, I, N, PL, Q, R.
- `snake_case` for modules/functions, `PascalCase` for classes.
- Tests in `tests/` directory, pattern `test_*.py`. Fixtures in `tests/fixtures/`.
