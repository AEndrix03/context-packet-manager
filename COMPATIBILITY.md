# Compatibility note

The new CPM vNext experience lives under `cpm_core/`, `cpm_cli/`, `cpm_builtin/`, and `cpm_plugins/`.
Those directories contain the minimal baseline described in the dev spec.

Legacy references:

- `cpm/`, `embedding_pool/`, and `registry/` contain the previous CPM runtime. They stay in the repository as reference material.
- `CPM.zip` is the zipped artifact from the prior iteration and should not be modified; treat it as a snapshot of the legacy project.

Use the legacy directories for migration context only; new development should own the `cpm_*` layout from this point forward.

## Legacy command aliases

The new `cpm` CLI is built on `cpm_core`, but it still supports the most-used legacy tokens via an alias layer defined in `cpm_core.compat`. When you run one of the following commands, `cpm` delegates the request to the parser under `cpm/src/cli`, so your old scripts keep working:

- `embed ...` (start/stop/status and configuration helpers managed by `cpm_cli/cli.py`)
- `lookup`
- `query`
- `publish`
- `install`
- `uninstall`
- `update`
- `use`
- `list-remote`
- `prune`
- `cache ...`
- `mcp ...`

`cpm doctor` prints this alias table every time it runs so you can double-check the mapping in a live workspace.

## Legacy layout detection

Modern workspaces expect `.cpm/packages/`, `.cpm/cache/`, `.cpm/plugins/`, `.cpm/state/`, and `.cpm/config/` (which hosts `config.yml` and `embeddings.yml`). When `cpm doctor` scans your workspace it now looks for directories under `.cpm` that still resemble the legacy layout (for example `.cpm/<packet>/manifest.json` or `.cpm/<packet>/docs.jsonl`). For every legacy artifact it reports a suggested migration path such as:

```
.cpm/my-packet-v1 -> .cpm/packages/my-packet/1.0.0
```

Run `cpm init` (again) after you move the legacy artifacts so that `cpm_core` rebuilds the expected hierarchy. This tool also warns when it finds `embeddings.yml` at the workspace root instead of inside `.cpm/config/`.
