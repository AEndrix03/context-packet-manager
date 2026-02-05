"""Tests for the built-in package manager helpers."""

from pathlib import Path

from cpm_builtin.packages import PackageManager
from cpm_builtin.packages.layout import version_dir


def _write_version(workspace_root: Path, name: str, version: str) -> None:
    path = version_dir(workspace_root, name, version)
    path.mkdir(parents=True, exist_ok=True)
    (path / "cpm.yml").write_text(f"name: {name}\nversion: {version}\n")


def test_resolve_version_prefers_pinned(tmp_path: Path) -> None:
    workspace = tmp_path / ".cpm"
    manager = PackageManager(workspace)

    for version in ("1.0.0", "1.1.0", "1.2.0-beta"):
        _write_version(workspace, "demo", version)

    manager.set_pinned_version("demo", "1.0.0")
    assert manager.resolve_version("demo", None) == "1.0.0"
    assert manager.resolve_version("demo", "latest") == "1.2.0-beta"

    resolved = manager.use("demo@latest")
    assert resolved == "1.2.0-beta"
    assert manager.get_active_version("demo") == "1.2.0-beta"


def test_prune_keeps_pinned_and_active(tmp_path: Path) -> None:
    workspace = tmp_path / ".cpm"
    manager = PackageManager(workspace)
    versions = ["0.9.0", "1.0.0", "1.1.0", "1.2.0"]
    for version in versions:
        _write_version(workspace, "demo", version)

    manager.set_pinned_version("demo", "1.1.0")
    manager.set_active_version("demo", "0.9.0")

    removed = manager.prune("demo", keep=1)
    assert removed == ["1.0.0"]
    assert not version_dir(workspace, "demo", "1.0.0").exists()
    assert version_dir(workspace, "demo", "1.1.0").exists()
    assert version_dir(workspace, "demo", "1.2.0").exists()
