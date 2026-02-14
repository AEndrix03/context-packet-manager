# OCI Publish And Install

## Publish
`PublishCommand` costruisce layout OCI (`build_oci_layout`) e invia artifact con `OciClient.push`.
Supporta `--no-embed` per distribuire packet senza vettori/FAISS.

## Install
`InstallCommand`:
1. risolve ref OCI,
2. scarica artifact,
3. copia payload in `.cpm/packages/<name>/<version>`,
4. seleziona provider/modello embedding (se necessario),
5. scrive install lock.

## Sicurezza
`cpm_core/oci/security.py` applica allowlist host, path safety e redazione token nei log.

## Operativita
Configurare `[oci]` in config (repository, retry, timeout, credenziali) prima di publish/install.
