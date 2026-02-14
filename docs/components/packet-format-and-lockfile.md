# Packet Format And Lockfile

## Artifact packet
- `docs.jsonl`: chunk e metadata.
- `vectors.f16.bin`: embedding in float16.
- `faiss/index.faiss`: indice vettoriale.
- `manifest.json`: metadata packet e checksums.

## Lockfile
`cpm-lock.json` include piano risolto (input, pipeline, modelli, hash artifact) e supporta verify deterministico.

## API chiave
- `render_lock`, `write_lock`, `load_lock`.
- `verify_lock_against_plan`, `verify_artifacts`.
- `lock_has_non_deterministic_sections` per `--frozen-lockfile`.

## Uso consigliato
- Aggiornare lock con `--update-lock` solo con modifiche intenzionali.
- Eseguire `build verify` in CI prima di publish.
