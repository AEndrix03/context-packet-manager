# Build Flow

## Entry point
`BuildCommand.run()` gestisce subazioni: `run`, `embed`, `verify`, `lock`, `inspect`, `describe`.

## Flusso run
1. merge configurazione CLI/workspace,
2. resolve builder entry,
3. crea/valida lockfile,
4. esegue builder,
5. aggiorna hash artifact nel lock.

## Flusso embed
Rigenera embeddings/FAISS partendo da packet gia materializzato (`docs.jsonl`) senza rifare chunking.

## Verify
Confronta lock atteso e artifact reali; fallisce con `--frozen-lockfile` se sezioni non deterministiche presenti.

## Checklist
- `--name` e `--version` obbligatori in run standard.
- usare `--update-lock` quando cambiano input/pipeline.
