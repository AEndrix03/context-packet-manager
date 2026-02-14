# Phase B - OCI Source, Verification, Lock Evolution

## Objective
Turn OCI into first-class query source with integrity/trust verification and lockfile provenance sections.

## Scope
1. Use OCI referrers API (fallback tags) for signature/SBOM/provenance discovery.
2. Verify cosign signature and parse CycloneDX/SPDX SBOM.
3. Track provenance (SLSA level metadata).
4. Extend lock payload with source trust evidence.

## Implementation Steps
1. Extend `cpm_core/oci/client.py` with referrers discovery helpers.
2. Add verification report models in `cpm_core/oci/types.py`.
3. Add verification helpers in `cpm_core/oci/security.py`.
4. Extend install lock payload with `signature`, `sbom`, `provenance`, `trust_score`.
5. Add lockfile loader/writer compatibility path for old payloads.

## Policy Default
Strict fail-closed:
1. If required signature is missing/invalid -> fail.
2. If required SBOM is missing/invalid -> fail.
3. If required provenance is missing -> fail.

## Tests
1. OCI source with valid signature and SBOM passes.
2. OCI source with invalid signature fails in strict mode.
3. Install/query preserve lock compatibility with legacy payloads.

## Risks
1. External dependency on `oras`/`cosign` tooling.
2. Registry-specific referrers support inconsistencies.
