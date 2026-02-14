# Phase F - Unified Policy Engine

## Objective
Apply one policy model across build/install/query/fetch.

## Scope
1. Add `.cpm/policy.yml` schema.
2. Support source allowlist, trust thresholds, token caps.
3. Enforce strict mode by default in CI.

## Implementation Steps
1. Create policy parser/validator module.
2. Integrate policy hooks in build/install/query/source resolver.
3. Add policy decision logging (allow/deny + reason).

## Tests
1. Deny non-allowlisted source.
2. Deny low trust score under strict threshold.
3. Warn-only mode allows execution with warning payload.
