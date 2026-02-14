# System Overview

## Obiettivo
CPM trasforma sorgenti testuali/codice in packet interrogabili per RAG: chunk -> embedding -> indice FAISS -> query.

## Moduli principali
- `cpm_cli/`: parser CLI e dispatch comandi.
- `cpm_core/`: runtime, registry feature, builtins, build/query/publish/install, packet I/O.
- `cpm_builtin/`: chunking, embeddings e helper packaging.
- `cpm_plugins/`: plugin first-party (`mcp`, `llm_builder`) caricati dinamicamente.
- `registry/src/`: servizio registry separato (API + metadata store).

## Architettura logica
1. `CPMApp` inizializza servizi e registri.
2. I builtins registrano command/builder/retriever di default.
3. `PluginManager` scopre plugin in workspace/user path e registra feature aggiuntive.
4. I comandi invocano feature via `FeatureRegistry` senza hard coupling ai plugin.

## Principi
- Estendibilita via plugin e registri.
- Pipeline deterministica con lockfile e hash artifact.
- Degrado controllato (fallback retriever/default provider).
