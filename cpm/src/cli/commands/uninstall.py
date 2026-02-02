from __future__ import annotations

import shutil
from pathlib import Path

from cli.core.cpm_pkg import (
    RegistryClient,
    normalize_latest,
    registry_latest_version,
    installed_versions,
    version_key,
    packet_root,
    version_dir,
    set_pinned_version,
)


def _parse_spec_optional(spec: str) -> tuple[str, str | None]:
    spec = (spec or "").strip()
    if not spec:
        raise SystemExit("[cpm:uninstall] missing spec")
    if "@" not in spec:
        return spec, None
    name, version = spec.split("@", 1)
    name = name.strip()
    version = normalize_latest(version)
    if not name:
        raise SystemExit("[cpm:uninstall] missing name")
    return name, version


def cmd_cpm_uninstall(args) -> None:
    cpm_dir = Path(args.cpm_dir or ".cpm").resolve()
    name, version = _parse_spec_optional(args.spec)

    root = packet_root(cpm_dir, name)
    if not root.exists():
        raise SystemExit(f"[cpm:uninstall] not installed: {name}")

    # No version => remove all
    if version is None:
        shutil.rmtree(root, ignore_errors=True)
        print(f"[cpm:uninstall] removed {name} (all versions)")
        return

    # latest => resolve from registry
    if version == "latest":
        registry = (getattr(args, "registry", "") or "").rstrip("/")
        if not registry:
            raise SystemExit("[cpm:uninstall] @latest requires --registry")
        client = RegistryClient(registry)
        version = registry_latest_version(client, name)
        print(f"[cpm:uninstall] resolved latest: {name}@{version}")

    vd = version_dir(cpm_dir, name, version)
    if not vd.exists():
        raise SystemExit(f"[cpm:uninstall] version not installed: {name}@{version}")

    shutil.rmtree(vd, ignore_errors=True)

    remaining = installed_versions(cpm_dir, name)
    if not remaining:
        shutil.rmtree(root, ignore_errors=True)
        print(f"[cpm:uninstall] removed {name}@{version} (no versions left, removed packet)")
        return

    new_pin = max(remaining, key=version_key)
    set_pinned_version(cpm_dir, name, new_pin)
    print(f"[cpm:uninstall] removed {name}@{version}; current={new_pin}")
