# Documentazione Tecnica

Questa cartella raccoglie la documentazione operativa e architetturale del progetto CPM.

## Indice rapido
- `architecture/system-overview.md`: panoramica moduli e dipendenze interne.
- `architecture/runtime-bootstrap.md`: bootstrap `CPMApp`, builtins e plugin loading.
- `architecture/feature-registry-and-services.md`: `FeatureRegistry`, `ServiceContainer`, event bus.
- `components/chunking-and-builders.md`: chunking router, default builder, LLM builder plugin.
- `components/embeddings-subsystem.md`: config provider, discovery, client OpenAI-compatible.
- `components/plugin-system.md`: discovery, precedence workspace/user, collision handling.
- `components/packet-format-and-lockfile.md`: `docs.jsonl`, vettori, manifest, lockfile.
- `components/oci-publish-install.md`: packaging OCI, publish/install, sicurezza.
- `flows/build-flow.md`: flusso `cpm build` e varianti (`embed`, `verify`, `lock`).
- `flows/query-flow.md`: flusso `cpm query`, retriever resolution e fallback.
- `flows/publish-install-flow.md`: ciclo distribuzione pacchetti via OCI.
- `operations/workspace-and-config.md`: layout `.cpm`, risoluzione config e override.
- `operations/testing-and-quality.md`: test strategy, lint, typing, check locali.
- `operations/registry-service.md`: servizio `registry/src` (API, storage, DB).
- `contributing/implementation-patterns.md`: pattern implementativi consigliati.
- `contributing/update-policy.md`: policy aggiornamento docs/README e commit.

## Quando leggere cosa
- Nuove feature CLI/plugin: partire da `architecture/*` e `contributing/implementation-patterns.md`.
- Correzioni su build/query: vedere `flows/*` e `components/*` relativi.
- Rilasci/distribuzione: leggere `components/oci-publish-install.md` e `flows/publish-install-flow.md`.
