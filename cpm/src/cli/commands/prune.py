from __future__ import annotations

import shutil
from pathlib import Path

from cli.core.cpm_pkg import installed_versions, version_key, version_dir, set_pinned_version


def cmd_cpm_prune(args) -> None:
    cpm_dir = Path(args.cpm_dir or ".cpm").resolve()
    name = args.name.strip()
    keep = int(args.keep)

    vs = installed_versions(cpm_dir, name)
    if not vs:
        raise SystemExit(f"[cpm:prune] not installed: {name}")

    vs_sorted = sorted(vs, key=version_key)
    to_keep = set(vs_sorted[-keep:]) if keep > 0 else set()
    to_remove = [v for v in vs_sorted if v not in to_keep]

    for v in to_remove:
        shutil.rmtree(version_dir(cpm_dir, name, v), ignore_errors=True)

    remaining = installed_versions(cpm_dir, name)
    pin = max(remaining, key=version_key) if remaining else None
    if pin:
        set_pinned_version(cpm_dir, name, pin)

    print(f"[cpm:prune] removed={len(to_remove)} kept={len(remaining)} current={pin}")
