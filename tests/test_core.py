"""Core runtime tests for workspace helpers and configuration."""

from pathlib import Path

from cpm_core.config import ConfigStore
from cpm_core.workspace import Workspace


def test_workspace_detects_existing(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    marker = project_dir / ".cpm"
    marker.mkdir()
    workspace = Workspace.find_workspace_root(start=project_dir)
    assert workspace.root == marker
    assert workspace.config_path.name == "config.toml"


def test_config_store_round_trips(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    store = ConfigStore(path=config_file)
    store.set("key", "value")
    assert store.get("key") == "value"
    assert store.get("missing", default="fallback") == "fallback"
