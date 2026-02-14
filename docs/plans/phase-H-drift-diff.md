# Phase H - Drift And Diff

## Objective
Detect semantic changes across packet versions and estimate retrieval impact.

## Scope
1. Add `cpm diff packet@v1 packet@v2`.
2. Add embedding drift score computation.
3. Add retrieval impact estimate (delta nDCG proxy).

## Implementation Steps
1. Build chunk-level semantic diff engine.
2. Compute vector drift metrics per chunk and aggregate.
3. Integrate drift report into CI regression checks.

## Tests
1. Diff reports added/removed/changed chunks.
2. Drift score is stable and deterministic.
3. CI threshold failure triggers non-zero exit code.
