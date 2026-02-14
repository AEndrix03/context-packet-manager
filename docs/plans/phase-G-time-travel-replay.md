# Phase G - Time Travel And Replay

## Objective
Enable reproducible historical queries and deterministic replay for audit.

## Scope
1. Add `--as-of` query option.
2. Resolve packet/source from historical lock snapshots.
3. Add `cpm replay <log>` command.

## Implementation Steps
1. Store timestamped lock snapshots.
2. Extend query resolver to load nearest snapshot <= timestamp.
3. Add replay log schema with source digest, model, reranker, output hash.

## Tests
1. `--as-of` resolves expected historical packet version.
2. Replay run reproduces same output hash under same environment.
3. Replay fails with explicit error if required artifacts are missing.
