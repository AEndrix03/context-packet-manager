"""Package manager primitives for the built-in CLI."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .io import read_simple_yml, write_simple_yml
from .layout import active_root, packages_root, pins_root, version_dir
from .versions import normalize_latest, split_version_parts, version_key

__all__ = [
    "PackageManager",
    "PackageSummary",
    "parse_package_spec",
]


@dataclass(frozen=True)
class PackageSummary:
    name: str
    versions: Sequence[str]
    pinned_version: Optional[str] = None
    active_version: Optional[str] = None


class PackageManager:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self.packages_dir = packages_root(self.workspace_root)
        self._pins_dir = pins_root(self.workspace_root)
        self._active_dir = active_root(self.workspace_root)
        self._ensure_paths()

    def _ensure_paths(self) -> None:
        for path in (self.packages_dir, self._pins_dir, self._active_dir):
            path.mkdir(parents=True, exist_ok=True)

    def list_packages(self) -> list[PackageSummary]:
        if not self.packages_dir.exists():
            return []
        names = sorted([p.name for p in self.packages_dir.iterdir() if p.is_dir()])
        summaries: list[PackageSummary] = []
        for name in names:
            versions = self.installed_versions(name)
            if not versions:
                continue
            summaries.append(
                PackageSummary(
                    name=name,
                    versions=versions,
                    pinned_version=self.get_pinned_version(name),
                    active_version=self.get_active_version(name),
                )
            )
        return summaries

    def installed_versions(self, name: str) -> list[str]:
        root = self.packages_dir / name
        if not root.exists():
            return []
        found: list[str] = []
        for manifest in root.rglob("cpm.yml"):
            if not manifest.is_file():
                continue
            meta = read_simple_yml(manifest)
            version = (meta.get("version") or "").strip()
            if version:
                found.append(version)
        return sorted(set(found), key=version_key)

    # ------------------------- pins -------------------------

    def get_pinned_version(self, name: str) -> Optional[str]:
        data = read_simple_yml(self._pin_path(name))
        version = (data.get("version") or "").strip()
        return version or None

    def set_pinned_version(self, name: str, version: str) -> None:
        split_version_parts(version)
        kv = {"name": name, "version": version}
        write_simple_yml(self._pin_path(name), kv)

    # ------------------------ active ------------------------

    def get_active_version(self, name: str) -> Optional[str]:
        data = read_simple_yml(self._active_path(name))
        version = (data.get("version") or "").strip()
        return version or None

    def set_active_version(self, name: str, version: str) -> None:
        split_version_parts(version)
        kv = {"name": name, "version": version}
        write_simple_yml(self._active_path(name), kv)

    # -------------------- resolution -----------------------

    def resolve_version(self, name: str, target: str | None = None) -> str:
        versions = self.installed_versions(name)
        if not versions:
            raise ValueError(f"no versions installed for {name}")
        candidate = normalize_latest(target)
        if candidate is None:
            pinned = self.get_pinned_version(name)
            if pinned and pinned in versions:
                return pinned
            return self._latest(versions)
        if candidate == "latest":
            return self._latest(versions)
        if candidate in versions:
            return candidate
        raise ValueError(f"version {candidate} is not installed for {name}")

    def _latest(self, versions: list[str]) -> str:
        return max(versions, key=version_key)

    def use(self, spec: str | None = None, *, name: str | None = None, version: str | None = None) -> str:
        if spec is not None:
            name_from_spec, version_from_spec = parse_package_spec(spec)
            name = name_from_spec
            version = version_from_spec
        if not name:
            raise ValueError("package name is required")
        resolved = self.resolve_version(name, version)
        self.set_pinned_version(name, resolved)
        self.set_active_version(name, resolved)
        return resolved

    # -------------------- housekeeping ---------------------

    def prune(self, name: str, *, keep: int = 1) -> list[str]:
        if keep < 1:
            raise ValueError("keep must be >= 1")
        versions = self.installed_versions(name)
        if not versions:
            return []
        keep_set = set(versions[-keep:])
        pinned = self.get_pinned_version(name)
        active = self.get_active_version(name)
        if pinned:
            keep_set.add(pinned)
        if active:
            keep_set.add(active)
        removed: list[str] = []
        for version in versions:
            if version in keep_set:
                continue
            path = version_dir(self.workspace_root, name, version)
            if path.exists():
                shutil.rmtree(path)
            removed.append(version)
        return removed

    def remove(self, name: str) -> None:
        root = self.packages_dir / name
        if root.exists():
            shutil.rmtree(root)
        for path in (self._pin_path(name), self._active_path(name)):
            if path.exists():
                path.unlink()

    # -------------------- helpers --------------------------

    def _pin_path(self, name: str) -> Path:
        return self._pins_dir / f"{name}.yml"

    def _active_path(self, name: str) -> Path:
        return self._active_dir / f"{name}.yml"


def parse_package_spec(spec: str) -> tuple[str, Optional[str]]:
    if "@" not in spec:
        return spec.strip(), None
    name, version = spec.split("@", 1)
    return name.strip(), version.strip() or None
