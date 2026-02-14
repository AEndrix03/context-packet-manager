# Runtime Bootstrap

## Sequenza
`CPMApp.bootstrap()` esegue:
1. registrazione plugin core,
2. registrazione builtins (`commands`, `builders`, `retrievers`),
3. `PluginManager.load_plugins()`,
4. emissione evento `bootstrap`,
5. ping registry client.

## Dettagli utili
- `_register_builtins()` e idempotente: evita doppie registrazioni.
- Lo stato ritornato (`CPMAppStatus`) include workspace, plugin attivi, comandi disponibili e stato registry.
- Il bootstrap dipende da `ServiceContainer` per risolvere servizi condivisi.

## Impatto pratico
Per debugging startup:
- verificare plugin discovery path,
- controllare collisioni feature,
- controllare ping registry.

Comando utile:
```powershell
cpm doctor
```
