# Repository Guidelines

## Mandatory Workflow (SerenaMCP)
- Use `SerenaMCP` as the default tool for analysis, code navigation, and edits.
- Before implementing, read the documentation under `docs/` for the relevant area and follow existing implementation patterns.
- Prefer extending existing modules (commands/builders/retrievers/plugins) over introducing parallel patterns.

## Project Structure
- `cpm_core/`: runtime, registry, builtins, packet/build/OCI internals.
- `cpm_cli/`: CLI parser and entrypoint wiring.
- `cpm_builtin/`: built-in chunking, embeddings, package helpers.
- `cpm_plugins/`: first-party plugins (`mcp`, `llm_builder`).
- `registry/src/`: standalone registry service.
- `tests/`: unit/integration tests and fixtures.
- `docs/`: architecture, flows, components, operations, contributing guides.

## Development Standards
- Python 3.11+, 4-space indentation, type hints on new/modified code.
- Naming: `snake_case` for modules/functions, `PascalCase` for classes.
- Keep behavior aligned with feature registry and plugin extension points.
- Quality gates: `black`, `ruff`, `mypy`, `pytest`.

## Documentation Policy
- After every relevant feature/change, update:
1. impacted documents in `docs/`
2. affected feature README(s) (`README.md` root and/or local module README)
3. command/config examples if behavior changed

## Commit Policy (Mandatory)
- After each relevant modification, create a dedicated commit.
- Use conventional prefixes: `feat|fix|docs|test|chore|refactor|perf|ci|build: <message>`.
- Keep commits atomic and scoped to one logical change.
- Avoid bundling unrelated changes in the same commit.
