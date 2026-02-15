# Query Flow

## Entry point
`QueryCommand.run()` risolve workspace, policy runtime (`policy.yml`), lock install (anche storico con `--as-of`), retriever richiesto/suggerito, source lazy (`--source`/`--registry`) e trasporto embedding.

## Pipeline
1. risoluzione retriever (`default` o plugin),
2. fallback automatico se retriever suggerito non presente,
3. opzionale: risoluzione `--source` oppure shortcut `--registry` (`dir://`, `oci://`, `https://`, repository OCI base) con fetch lazy in cache CAS locale (`.cpm/cache/objects/<digest>`),
4. per source OCI: verifica trust (signature/SBOM/provenance) prima della materializzazione in strict mode,
5. invocazione retriever con indexer/reranker selezionati,
6. context compiler strutturato (`outline/core_snippets/glossary/risks/citations`) con token cap,
7. policy enforcement su trust e token budget,
8. output testuale o JSON + replay log deterministico (`state/replay/query-*.json`).

## Retriever nativi
- `NativeFaissRetriever`
- indexer `FaissFlatIPIndexer`
- indexer `hybrid-rrf` (dense + BM25 + RRF)
- reranker `NoopReranker` / `TokenDiversityReranker`

## Osservazioni
Il flusso resta robusto con install lock incompleti e plugin mancanti, mantenendo fallback al retriever di default.
Quando viene usato `--source`, `query` materializza prima un packet locale in cache e poi interroga il retriever nativo su quel path.
Il payload include metadata sorgente estesi (`trust_score`, `verification`, `refs`, `trust`) quando disponibili.
