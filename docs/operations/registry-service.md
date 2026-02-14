# Registry Service

## Scopo
`registry/src` fornisce API HTTP per metadata package/version e storage artifact, separato dal core CLI.

## Componenti
- `api.py`: endpoint health, publish, download, yank, list.
- `database.py`: schema SQL e operazioni su versioni pacchetto.
- `storage.py`: backend oggetti (`S3Storage`).
- `settings.py`: caricamento ambiente/config runtime.
- `cli.py`: start/stop/status servizio con PID/log file.

## Endpoint Hub context-supply-chain
- `POST /v1/resolve`: risolve `uri -> digest` e ritorna metadata trust/refs (cache lato DB).
- `POST /v1/policy/evaluate`: valuta policy runtime (`strict|warn`, allowlist, trust threshold).
- `GET /v1/capabilities`: capability negotiation per verifica/policy/retrieval.

Il DB mantiene tabelle dedicate (`source_resolutions`, `policy_decisions`) oltre allo schema packages/versioni.

## Integrazione CLI locale
- `cpm install` e `cpm query` applicano sempre policy locale (`policy.yml`).
- Se `config.toml` contiene `[hub].url`, viene eseguita anche valutazione remota su `/v1/policy/evaluate`.
- `enforce_remote_policy = true` abilita fail-closed se Hub non risponde/risponde invalido.

## Note operative
- inizializzare schema prima della prima pubblicazione,
- monitorare stato processo via `registry/src/cli.py status`.
