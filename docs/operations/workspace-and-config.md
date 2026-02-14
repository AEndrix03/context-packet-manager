# Workspace And Config

## Layout `.cpm`
- `config/` (es. `embeddings.yml`)
- `packages/`
- `plugins/`
- file stato lock/install.

## Risoluzione config
`WorkspaceResolver` combina:
1. override env,
2. override root espliciti,
3. config workspace,
4. config user fallback.

## Buone pratiche
- mantenere config sensibile fuori dal controllo versione,
- usare provider default esplicito,
- verificare path assoluti/relativi in ambienti CI.

## Comandi
```powershell
cpm init
cpm doctor
```

## Policy runtime
`policy.yml` (in root workspace `.cpm/`) abilita enforcement unificato su query/install/source:

```yaml
policy:
  mode: strict
  allowed_sources:
    - oci://registry.local/*
  min_trust_score: 0.8
  max_tokens: 6000
```

`mode: warn` permette esecuzione con warning per strict failures.

## Replay e audit
- Query salva replay log deterministico in `.cpm/state/replay/query-<timestamp>.json`.
- `cpm replay <log>` ricalcola output hash e verifica riproducibilita.
