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
