# Task Completion Checks
- Run relevant tests with `pytest` in the component directory when changes warrant it.
- Ensure Ruff/Black conventions are respected (line length 120 in `cpm/` and `registry/`, 110 in `embedding_pool/`).
- If touching config or storage, call it out explicitly (e.g., `.cpm/*`, `registry/.env`, `registry/registry.db*`).
- Avoid committing new/modified registry DB artifacts unless explicitly required.
- Note any entrypoint or CLI changes in the summary (e.g., `cpm`, `cpm-registry`, `cpm mcp serve`).