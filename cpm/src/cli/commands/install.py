from __future__ import annotations

import logging
from pathlib import Path

from cli.core.cpm_pkg import (
    RegistryClient,
    normalize_latest,
    registry_latest_version,
    download_and_extract,
    set_pinned_version,
)


def _parse_spec_optional(spec: str) -> tuple[str, str | None]:
    spec = (spec or "").strip()
    if not spec:
        raise SystemExit("[cpm:install] missing spec")
    if "@" not in spec:
        return spec, None
    name, version = spec.split("@", 1)
    name = name.strip()
    version = normalize_latest(version)
    if not name:
        raise SystemExit("[cpm:install] missing name")
    return name, version


def cmd_cpm_install(args) -> None:
    logging.basicConfig(level=logging.INFO)
    cpm_dir = Path(args.cpm_dir or ".cpm").resolve()
    registry = (args.registry or "").rstrip("/")
    if not registry:
        raise SystemExit("[cpm:install] missing --registry")

    name, version = _parse_spec_optional(args.spec)

    client = RegistryClient(registry)

    # missing or latest => semantic latest
    if version is None or version == "latest":
        version = registry_latest_version(client, name)
        print(f"[cpm:install] resolved latest: {name}@{version}")

    if not client.exists(name, version):
        raise SystemExit(f"[cpm:install] not found on registry: {name}@{version}")

    vd = download_and_extract(client, name, version, cpm_dir)
    set_pinned_version(cpm_dir, name, version)

    print(f"[cpm:install] installed {name}@{version}")
    print(f"[cpm:install] dir={vd.as_posix()}")
