from __future__ import annotations

import tempfile
from pathlib import Path

from cli.core.cpm_pkg import (
    RegistryClient,
    verify_built_packet_dir,
    read_built_meta,
    make_versioned_tar_from_build_dir,
)


def cmd_cpm_publish(args) -> None:
    src_dir = Path(args.from_dir or ".").resolve()
    if not src_dir.exists() or not src_dir.is_dir():
        raise SystemExit(f"[cpm:publish] --from must be a directory: {src_dir}")

    verify_built_packet_dir(src_dir)
    name, version = read_built_meta(src_dir)

    registry = (args.registry or "").rstrip("/")
    if not registry:
        raise SystemExit("[cpm:publish] missing --registry")

    client = RegistryClient(registry)

    exists = client.exists(name, version)
    if exists and not args.overwrite:
        raise SystemExit(
            f"[cpm:publish] {name}@{version} already exists on registry.\n"
            f"Use --overwrite to replace it."
        )

    if exists and args.overwrite and not getattr(args, "yes", False):
        answer = input(
            f"Package {name}@{version} already exists on registry.\n"
            f"Overwrite? [y/N]: "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("[cpm:publish] aborted")
            return

    with tempfile.TemporaryDirectory(prefix="cpm-tar-") as tmpd:
        tar_path = Path(tmpd) / f"{name}-{version}.tar.gz"
        make_versioned_tar_from_build_dir(src_dir, name, version, tar_path)
        res = client.publish(name, version, str(tar_path), overwrite=bool(args.overwrite))

    print(f"[cpm:publish] ok {name}@{version} sha256={res.sha256} size={res.size_bytes}")
