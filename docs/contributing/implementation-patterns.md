# Implementation Patterns

## Prima di implementare
1. Risolvere il punto d'estensione corretto (`command`, `builder`, `retriever`, plugin).
2. Verificare pattern esistente nei moduli fratelli (stessa area funzionale).
3. Allineare naming, error handling e output CLI ai builtins gia presenti.

## Pattern consigliati
- Dipendenze runtime passate tramite container/context, evitare global state.
- Feature registrate nel registry, non chiamate statiche hardcoded.
- Fallback espliciti con messaggi diagnostici utili.
- Lock/hash aggiornati per mantenere determinismo pipeline.

## Anti-pattern
- bypass del `FeatureRegistry`,
- plugin con side-effect all'import,
- modifica silente di artifact senza aggiornare lock/manifest.
