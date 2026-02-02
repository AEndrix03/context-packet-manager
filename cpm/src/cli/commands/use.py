from __future__ import annotations

from pathlib import Path

from cli.core.cpm_pkg import (
    RegistryClient,
    normalize_latest,
    registry_latest_version,
    version_dir,
    set_pinned_version,
)


def _parse_spec(spec: str) -> tuple[str, str]:
    spec = (spec or "").strip()
    if "@" not in spec:
        raise SystemExit("[cpm:use] expected name@<version|latest>")
    name, version = spec.split("@", 1)
    name = name.strip()
    version = normalize_latest(version) or ""
    if not name or not version:
        raise SystemExit("[cpm:use] expected name@<version|latest>")
    return name, version


def cmd_cpm_use(args) -> None:
    cpm_dir = Path(args.cpm_dir or ".cpm").resolve()
    name, version = _parse_spec(args.spec)

    if version == "latest":
        registry = (getattr(args, "registry", "") or "").rstrip("/")
        if not registry:
            raise SystemExit("[cpm:use] @latest requires --registry")
        client = RegistryClient(registry)
        version = registry_latest_version(client, name)
        print(f"[cpm:use] resolved latest: {name}@{version}")

    vd = version_dir(cpm_dir, name, version)
    if not vd.exists():
        raise SystemExit(f"[cpm:use] version not installed locally: {name}@{version}")

    set_pinned_version(cpm_dir, name, version)
    print(f"[cpm:use] current={name}@{version}")
