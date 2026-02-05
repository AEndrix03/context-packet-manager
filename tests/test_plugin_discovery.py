"""Integration tests for plugin discovery and error isolation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cpm_core.events import EventBus
from cpm_core.paths import UserDirs
from cpm_core.plugin import PluginManager, PluginState
from cpm_core.registry import FeatureNotFoundError
from cpm_core.workspace import Workspace


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "plugins"


def _create_workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / ".cpm"
    root.mkdir()
    config = root / "config.toml"
    config.write_text("")
    return Workspace(root=root, config_path=config)


def _copy_fixture(name: str, destination: Path) -> None:
    source = FIXTURE_ROOT / name
    shutil.copytree(source, destination)


def _build_manager(tmp_path: Path, workspace: Workspace) -> PluginManager:
    user_data = tmp_path / "user_data"
    return PluginManager(
        workspace=workspace,
        events=EventBus(),
        user_dirs=UserDirs(data_dir_override=user_data),
    )


def test_sample_plugin_registers_features(tmp_path: Path) -> None:
    workspace = _create_workspace(tmp_path)
    plugins_dir = workspace.root / "plugins"
    plugins_dir.mkdir()
    _copy_fixture("sample_plugin", plugins_dir / "sample_plugin")

    manager = _build_manager(tmp_path, workspace)
    manager.register("core")
    manager.load_plugins()

    assert manager.list_plugins() == ("core", "sample_plugin")

    command_entry = manager.registry.resolve("sample-command")
    assert command_entry.group == "sample"
    assert command_entry.origin == "sample_plugin"

    builder_entry = manager.registry.resolve("sample-builder")
    assert builder_entry.origin == "sample_plugin"

    record = next(rec for rec in manager.plugin_records() if rec.id == "sample_plugin")
    assert record.state == PluginState.READY
    assert len(record.features) == 2


def test_workspace_plugin_overrides_user_plugin(tmp_path: Path) -> None:
    workspace = _create_workspace(tmp_path)
    plugins_dir = workspace.root / "plugins"
    plugins_dir.mkdir()
    _copy_fixture("override_workspace", plugins_dir / "override_plugin")

    user_plugins_dir = tmp_path / "user_data" / "plugins"
    user_plugins_dir.mkdir(parents=True)
    _copy_fixture("override_user", user_plugins_dir / "override_plugin")

    manager = _build_manager(tmp_path, workspace)
    manager.register("core")
    manager.load_plugins()

    assert manager.list_plugins() == ("core", "override_plugin")

    workspace_entry = manager.registry.resolve("override-workspace")
    assert workspace_entry.origin == "override_plugin"

    with pytest.raises(FeatureNotFoundError):
        manager.registry.resolve("override-user")

    record = next(rec for rec in manager.plugin_records() if rec.id == "override_plugin")
    assert record.source == "workspace"
    assert record.state == PluginState.READY


def test_failing_plugin_does_not_block_startup(tmp_path: Path) -> None:
    workspace = _create_workspace(tmp_path)
    plugins_dir = workspace.root / "plugins"
    plugins_dir.mkdir()
    _copy_fixture("failing_plugin", plugins_dir / "failing_plugin")

    manager = _build_manager(tmp_path, workspace)
    manager.register("core")
    manager.load_plugins()

    assert manager.list_plugins() == ("core", "failing_plugin")

    record = next(rec for rec in manager.plugin_records() if rec.id == "failing_plugin")
    assert record.state == PluginState.FAILED
    assert "unable to initialize" in record.error

    assert manager.registry.display_names() == ()
