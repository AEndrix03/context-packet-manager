# Query Flow

## Entry point
`QueryCommand.run()` risolve workspace, lock install, retriever richiesto/suggerito e trasporto embedding.

## Pipeline
1. risoluzione retriever (`default` o plugin),
2. fallback automatico se retriever suggerito non presente,
3. invocazione retriever con indexer/reranker selezionati,
4. output testuale o JSON.

## Retriever nativi
- `NativeFaissRetriever`
- indexer `FaissFlatIPIndexer`
- reranker `NoopReranker` / `TokenDiversityReranker`

## Osservazioni
Il flusso e robusto a install lock incompleti e a plugin mancanti, mantenendo fallback al retriever di default.
