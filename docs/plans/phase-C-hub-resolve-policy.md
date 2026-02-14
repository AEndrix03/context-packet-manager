# Phase C - Hub Resolve API And Policy

## Objective
Upgrade `registry/src` from package metadata service to context resolution and policy decision hub.

## Scope
1. Add `/v1/resolve` endpoint for source-to-digest resolution.
2. Add `/v1/policy/evaluate` endpoint.
3. Add `/v1/capabilities` endpoint for runtime feature negotiation.
4. Persist trust/policy metadata in SQLite.

## API Contracts
1. `POST /v1/resolve` request: `{ "uri": "..." }`
2. `POST /v1/resolve` response: `{ "uri": "...", "digest": "...", "refs": [...], "trust": {...} }`
3. `POST /v1/policy/evaluate` request: context + policy inputs.
4. `GET /v1/capabilities` response: supported verification/retrieval capabilities.

## Implementation Steps
1. Extend `registry/src/database.py` schema for source/trust/policy tables.
2. Extend `registry/src/api.py` with new handlers.
3. Add simple policy evaluator in `registry/src`.
4. Integrate `HubSource` client usage from query runtime.

## Tests
1. Resolve returns digest for known source.
2. Policy evaluate returns deny for strict violations.
3. Capabilities endpoint reflects configured features.

## Risks
1. Hub policy drift from local CLI policy defaults.
2. Endpoint latency impacting TTFN.
