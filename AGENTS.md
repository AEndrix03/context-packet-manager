# Repository Guidelines

## Project Structure and Module Organization
- `cpm/`: Core Context Packet Manager package, CLI, and chunkers. Source in `cpm/src/`.
- `embedding_pool/`: Embedding Pool server and runtime. Source in `embedding_pool/src/`.
- `registry/`: CPM Registry service and storage. Source in `registry/src/`.
- `.cpm/`: Local runtime configuration and cache created by `cpm init`.
- `.venv/`: Local virtual environment (not tracked).

## Build, Test, and Development Commands
- `python -m venv .venv` and `pip install -e ./cpm` (or `./embedding_pool`, `./registry`): set up editable installs.
- `cpm init`: create `.cpm/config.yml` and `.cpm/pool.yml`.
- `cpm embed start-server --detach`: run the embedding server locally.
- `cpm build --input-dir ./docs --packet-dir ./packets/example --model jina-en --version 1.0.0`: build a packet.
- `cpm query --packet example --query "..." -k 5`: query a packet.
- `cpm-registry start --detach`: run the registry service.
- `pytest`: run tests inside a component directory (when tests exist).

## Coding Style and Naming Conventions
- Python 3.10-3.12, type hints encouraged.
- Ruff is configured in each `pyproject.toml` (line length 120 in `cpm/` and `registry/`, 110 in `embedding_pool/`).
- Black is configured in `cpm/` and `registry/`.
- Module and function names use `snake_case`; classes use `PascalCase`.

## Testing Guidelines
- Pytest configuration lives in each component `pyproject.toml`.
- Test file patterns: `test_*.py` or `*_test.py`.
- Add tests under `cpm/tests/`, `embedding_pool/tests/`, or `registry/tests/` as appropriate.
- Coverage reporting is enabled for `cpm/` and `registry/` (see `--cov` settings).

## Commit and Pull Request Guidelines
- Commit history mixes conventional prefixes (`feat:`) and short informal messages (`wip`, `amend`). Use concise, present-tense summaries; prefer `type: summary` for new work.
- PRs should include: a clear description, linked issues (if any), and steps to run or verify locally.
- If you touch config or storage, call it out explicitly (for example, `.cpm/*`, `registry/.env`, or `registry/registry.db*`).

## Configuration and Data Notes
- Local config: `.cpm/config.yml` and `.cpm/pool.yml`.
- Registry runtime uses SQLite files in `registry/`; avoid committing new or modified DB artifacts unless explicitly required.
