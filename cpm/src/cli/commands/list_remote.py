from __future__ import annotations

import json

from cli.core.cpm_pkg import RegistryClient, version_key, registry_latest_version


def cmd_cpm_list_remote(args) -> None:
    registry = (args.registry or "").rstrip("/")
    if not registry:
        raise SystemExit("[cpm:list-remote] missing --registry")

    client = RegistryClient(registry)
    data = client.list(args.name, include_yanked=getattr(args, "include_yanked", False))

    versions = data.get("versions") or []

    if getattr(args, "sort_semantic", False):
        versions = sorted(versions, key=lambda x: version_key(str(x.get("version", ""))), reverse=True)

    if args.format == "json":
        print(json.dumps({"name": args.name, "versions": versions}, ensure_ascii=False, indent=2))
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
        ver = v.get("version")
        mark = " *latest*" if latest and ver == latest else ""
        print(
            f"{args.name}@{ver} sha256={v.get('sha256')} size={v.get('size_bytes')} "
            f"published_at={v.get('published_at')} yanked={v.get('yanked')}{mark}"
        )
