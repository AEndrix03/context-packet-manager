# Feature Registry And Services

## FeatureRegistry
`FeatureRegistry` centralizza la registrazione e risoluzione di feature (`command`, `builder`, `retriever`) con supporto a nomi qualificati/non qualificati.

## ServiceContainer
`ServiceContainer` gestisce provider lazy/eager per dipendenze runtime. Permette di evitare import circolari e ridurre coupling tra moduli.

## EventBus
`EventBus` supporta subscribe/emit con eventi standard (`pre_discovery`, `post_discovery`, `pre_plugin_init`, `post_plugin_init`, `bootstrap`).

## Pattern operativo
- Registrare feature una sola volta.
- Esporre dipendenze via container, non via global state.
- Usare eventi per telemetria e diagnostica, non per logica critica non deterministica.
