# Phase A - Sources And CAS

## Objective
Introduce source abstraction (`dir://`, `oci://`, `https://`) and content-addressed cache for query-time packet materialization.

## Scope
1. Add `cpm_core/sources` package with source protocol and resolver.
2. Integrate `cpm query --source` without breaking `--packet`.
3. Store materialized packet payload in `.cpm/cache/objects/<digest>`.
4. Add source/cache telemetry events.

## Interfaces
1. `CPMSource.can_handle(uri: str) -> bool`
2. `CPMSource.resolve(uri: str) -> PacketReference`
3. `CPMSource.fetch(ref, cache) -> LocalPacket`
4. `CPMSource.check_updates(ref) -> UpdateInfo`

## Implementation Steps
1. Add models: `PacketReference`, `LocalPacket`, `UpdateInfo`.
2. Add `SourceCache` with digest-keyed object storage and eviction policy.
3. Implement `DirSource`, `OciSource`, `HubSource`.
4. Add `SourceResolver.resolve_and_fetch`.
5. Update query command parser/run flow.
6. Emit source/cache info in query output JSON and text mode.

## Tests
1. Query accepts `--source dir://...` and passes local cached path to retriever.
2. Missing `--packet` and `--source` fails with explicit error.
3. Existing `--packet` behavior unchanged.

## Risks
1. Cache growth without strict quotas.
2. Source URI parsing differences across platforms.
3. Long cold-start for remote archives.
