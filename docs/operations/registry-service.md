# Registry Service

## Scopo
`registry/src` fornisce API HTTP per metadata package/version e storage artifact, separato dal core CLI.

## Componenti
- `api.py`: endpoint health, publish, download, yank, list.
- `database.py`: schema SQL e operazioni su versioni pacchetto.
- `storage.py`: backend oggetti (`S3Storage`).
- `settings.py`: caricamento ambiente/config runtime.
- `cli.py`: start/stop/status servizio con PID/log file.

## Note operative
- inizializzare schema prima della prima pubblicazione,
- monitorare stato processo via `registry/src/cli.py status`.
