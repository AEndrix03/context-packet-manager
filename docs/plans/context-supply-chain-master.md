# CPM Context Supply-Chain Master Plan

## Goal
Evolve CPM from packet builder/runtime into a trust-aware context supply-chain engine while keeping CLI-first, local-first, and plugin compatibility guarantees.

## Delivery Model
1. Phase A-C are delivery-critical and should be implemented first.
2. Phase D-H are innovation layers that can proceed in parallel after A-C interfaces stabilize.
3. Every phase must ship with tests, docs, and atomic commits.

## Compatibility Contract
1. Keep existing commands compatible: `build`, `query`, `install`, `publish`.
2. Preserve extension points: `FeatureRegistry`, `PluginManager`, `ServiceContainer`, `EventBus`, `DefaultBuilder`.
3. Extend lockfile/manifest schema in a backward-compatible way.

## KPIs
1. TTFN <= 10s cold, <= 5s cached.
2. nDCG@5 +15% vs dense-only baseline.
3. Citation coverage 100%.
4. Trust policy violations in strict mode: 0.

## Phase Files
1. `docs/plans/phase-A-sources-cas.md`
2. `docs/plans/phase-B-oci-source-verify-lock.md`
3. `docs/plans/phase-C-hub-resolve-policy.md`
4. `docs/plans/phase-D-hybrid-retrieval.md`
5. `docs/plans/phase-E-context-compiler.md`
6. `docs/plans/phase-F-policy-engine.md`
7. `docs/plans/phase-G-time-travel-replay.md`
8. `docs/plans/phase-H-drift-diff.md`

## Global Quality Gates
1. `python -m pytest -q`
2. `python -m ruff check .`
3. `python -m mypy cpm_core cpm_cli cpm_builtin cpm_plugins`
4. Update `README.md` + impacted docs for each behavior change.
