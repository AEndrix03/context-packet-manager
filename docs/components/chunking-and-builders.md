# Chunking And Builders

## Chunking
`ChunkerRouter` seleziona il chunker in base al tipo file: AST/tree-sitter quando disponibile, fallback testuale altrimenti.

## Default Builder
`DefaultBuilder.build()`:
1. valida source/destination,
2. scansiona file e chunk,
3. materializza packet (`docs.jsonl`, vettori, FAISS, manifest),
4. produce output incrementale quando possibile.

## LLM Builder Plugin
`cpm_plugins/llm_builder` introduce una pipeline alternativa (pre-chunk, classificazione, arricchimento, postprocess) configurabile via `config.yml`.

## Estensione
Per aggiungere un builder:
- implementare entrypoint plugin,
- registrare feature nel registry,
- mantenere compatibilita con lock/manifest artifacts.
