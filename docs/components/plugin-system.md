# Plugin System

## Discovery e precedence
`PluginManager` scopre plugin in path workspace e user, prepara i candidati e applica precedenza dichiarata (override controllati).

## Load lifecycle
Per ogni candidato:
1. prepara `PluginContext`,
2. carica entrypoint via `PluginLoader`,
3. registra feature,
4. marca stato `READY` o `FAILED` con errore.

## Collision handling
Collisioni di feature generano `FeatureCollisionError`: il plugin fallisce ma il runtime continua con gli altri plugin.

## Requisiti plugin
- `plugin.toml` valido,
- hook chiari in entrypoint (`init`/activate),
- dipendenze minime per non degradare CLI baseline.
