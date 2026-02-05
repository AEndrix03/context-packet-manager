# Contributing to CPM vNext

## Getting started

1. Install dependencies (`python -m pip install -e .`).
2. Run unit tests with `pytest`.
3. Keep black/ruff/mypy/pytest passing when working on new code.

## Plugin conventions

- Official plugins live under `cpm_plugins/` and should be discoverable via the `PluginManager`.
- Package names for optional components should follow the `cpm-<feature>` pattern to keep them distinguishable from third-party plugins.
- Each plugin must register through the plugin manager and expose a clear `activate` or `connect` hook.
- Keep plugin dependencies light or optional so that the baseline CLI remains runnable with `pip install -e .`.

## Naming conventions

- Python modules use `snake_case`; classes use `PascalCase`.
- CLI commands mirror features in `cpm_builtin` (`build`, `query`, `pkg`, `embed`, `status`).
- Experimental or internal helpers should live under an `experimental` subpackage and stay out of the public API.

## Compatibility notes

- The legacy codebase (`cpm/`, `embedding_pool/`, `registry/`, and `CPM.zip`) stays in the repository as a reference for the previous architecture.
- When updating core behavior, document the gap between the new lightweight runtime and the legacy implementation so curiosity-driven contributors can follow the transition.
