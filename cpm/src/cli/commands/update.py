from __future__ import annotations

import shutil
from pathlib import Path

from cli.core.cpm_pkg import (
    RegistryClient,
    normalize_latest,
    registry_latest_version,
    packet_root,
    download_and_extract,
    set_pinned_version,
)


def _parse_spec_optional(spec: str) -> tuple[str, str | None]:
    spec = (spec or "").strip()
    if not spec:
        raise SystemExit("[cpm:update] missing spec")
    if "@" not in spec:
        return spec, None
    name, version = spec.split("@", 1)
    name = name.strip()
    version = normalize_latest(version)
    if not name:
        raise SystemExit("[cpm:update] missing name")
    return name, version


def cmd_cpm_update(args) -> None:
    cpm_dir = Path(args.cpm_dir or ".cpm").resolve()
    registry = (args.registry or "").rstrip("/")
    if not registry:
        raise SystemExit("[cpm:update] missing --registry")

    name, requested = _parse_spec_optional(args.spec)

    root = packet_root(cpm_dir, name)
    if not root.exists():
        raise SystemExit(f"[cpm:update] {name} not installed. Run: rag cpm install {name} --registry {registry}")

    client = RegistryClient(registry)

    version = requested
    if version is None or version == "latest":
        version = registry_latest_version(client, name)
        print(f"[cpm:update] resolved latest: {name}@{version}")
    else:
        if not client.exists(name, version):
            raise SystemExit(f"[cpm:update] not found on registry: {name}@{version}")

    if getattr(args, "purge", False):
        shutil.rmtree(root, ignore_errors=True)

    vd = download_and_extract(client, name, version, cpm_dir)
    set_pinned_version(cpm_dir, name, version)

    print(f"[cpm:update] ok {name}@{version}")
    print(f"[cpm:update] dir={vd.as_posix()}")
