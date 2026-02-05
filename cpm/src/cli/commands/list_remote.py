from __future__ import annotations

import json
from cli.core.cpm_pkg import RegistryClient, version_key, registry_latest_version


def cmd_cpm_list_remote(args) -> None:
    registry = (args.registry or "").rstrip("/")
    if not registry:
        raise SystemExit("[cpm:list-remote] missing --registry")

    client = RegistryClient(registry)
    data = client.list(args.name, include_yanked=getattr(args, "include_yanked", False))

    versions = data.versions

    if getattr(args, "sort_semantic", False):
        versions = sorted(
            versions,
            key=lambda v: version_key(v.version or ""),
            reverse=True,
        )

    if args.format == "json":
        print(
            json.dumps(
                {"name": data.name or args.name, "versions": [v.to_dict() for v in versions]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not versions:
        print("(no versions)")
        return

    latest = None
    try:
        latest = registry_latest_version(client, args.name)
    except Exception:
        latest = None

    for v in versions:
        ver = v.version or "<unknown>"
        mark = " *latest*" if latest and ver == latest else ""
        print(
            f"{args.name}@{ver} sha256={v.sha256} size={v.size_bytes} "
            f"published_at={v.published_at} yanked={v.yanked}{mark}"
        )
