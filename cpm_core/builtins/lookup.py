"""Built-in lookup command for inspecting built packet metadata."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from cpm_builtin.packages.versions import version_key
from cpm_core.api import cpmcommand

from .commands import _WorkspaceAwareCommand


def _read_simple_yml(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out
    except UnicodeDecodeError:
        lines = path.read_text(encoding="latin-1").splitlines()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


@cpmcommand(name="lookup", group="cpm")
class LookupCommand(_WorkspaceAwareCommand):
    """List packets under a destination root with metadata and health status."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument(
            "--destination",
            default="packages",
            help="Installed packets root (default: ./packages under workspace, i.e. ./.cpm/packages from project root)",
        )
        parser.add_argument(
            "--all-versions",
            action="store_true",
            help="Include all versions per package (default: latest only)",
        )
        parser.add_argument("--format", choices=["text", "json"], default="text")

    def run(self, argv: Any) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        self.workspace_root = workspace_root
        destination_raw = str(getattr(argv, "destination", "packages") or "packages")
        destination = Path(destination_raw)
        if not destination.is_absolute() and workspace_root.name == ".cpm":
            parts = destination.parts
            if len(parts) > 0 and parts[0] == ".cpm":
                destination = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        root = destination if destination.is_absolute() else (workspace_root / destination)

        packets = self._collect_packets(root=root, include_all_versions=bool(getattr(argv, "all_versions", False)))
        if getattr(argv, "format", "text") == "json":
            print(json.dumps({"ok": True, "root": str(root), "count": len(packets), "packets": packets}, indent=2))
            return 0

        if not packets:
            print(f"[cpm:lookup] no installed packets found under {root}")
            return 0

        print(f"[cpm:lookup] root={root} installed_packets={len(packets)}")
        for item in packets:
            status = "ok" if item["is_valid"] else "incomplete"
            print(
                f"[cpm:lookup] {item['name']}@{item['version']} status={status} "
                f"docs={item['docs']} vectors={item['vectors']} description={item['description']}"
            )
            print(f"[cpm:lookup] path={item['path']}")
        return 0

    def _collect_packets(self, *, root: Path, include_all_versions: bool) -> list[dict[str, Any]]:
        if not root.exists() or not root.is_dir():
            return []

        packets: list[dict[str, Any]] = []
        for name_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            versions = [path for path in name_dir.iterdir() if path.is_dir()]
            if not versions:
                continue
            versions.sort(key=lambda path: version_key(path.name))
            selected = versions if include_all_versions else [versions[-1]]
            for version_dir in selected:
                packets.append(self._packet_info(version_dir))

        packets.sort(key=lambda item: (str(item["name"]), version_key(str(item["version"]))))
        return packets

    def _packet_info(self, packet_dir: Path) -> dict[str, Any]:
        manifest_path = packet_dir / "manifest.json"
        cpm_yml_path = packet_dir / "cpm.yml"
        docs_path = packet_dir / "docs.jsonl"
        vectors_path = packet_dir / "vectors.f16.bin"
        faiss_path = packet_dir / "faiss" / "index.faiss"

        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        yml = _read_simple_yml(cpm_yml_path)
        cpm_meta = manifest.get("cpm") if isinstance(manifest.get("cpm"), dict) else {}
        counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}

        name = yml.get("name") or cpm_meta.get("name") or packet_dir.parent.name
        version = yml.get("version") or cpm_meta.get("version") or packet_dir.name
        if str(name).strip() == str(version).strip() and packet_dir.parent.name.strip() != str(name).strip():
            # Some older packets persisted the version into `name`; use directory layout as a safer display fallback.
            name = packet_dir.parent.name
        description = yml.get("description") or cpm_meta.get("description") or ""
        docs_count = counts.get("docs")
        vectors_count = counts.get("vectors")

        return {
            "name": str(name),
            "version": str(version),
            "description": str(description),
            "path": str(packet_dir.resolve()).replace("\\", "/"),
            "docs": int(docs_count) if isinstance(docs_count, int) else None,
            "vectors": int(vectors_count) if isinstance(vectors_count, int) else None,
            "is_valid": manifest_path.exists() and cpm_yml_path.exists() and docs_path.exists() and vectors_path.exists() and faiss_path.exists(),
        }
