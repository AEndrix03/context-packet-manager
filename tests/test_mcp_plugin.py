"""Integration tests for the CPM MCP plugin."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest

from cpm_core.events import EventBus
from cpm_core.paths import UserDirs
from cpm_core.plugin import PluginManager
from cpm_core.workspace import Workspace


def _create_workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / ".cpm"
    root.mkdir()
    config = root / "config.toml"
    config.write_text("")
    return Workspace(root=root, config_path=config)


def _build_manager(tmp_path: Path, workspace: Workspace) -> PluginManager:
    user_data = tmp_path / "user_data"
    return PluginManager(
        workspace=workspace,
        events=EventBus(),
        user_dirs=UserDirs(data_dir_override=user_data),
    )


def _install_plugin(workspace: Workspace) -> None:
    destination = workspace.root / "plugins" / "mcp"
    shutil.copytree(Path("cpm_plugins") / "mcp", destination)


def test_mcp_plugin_registers_command(tmp_path: Path) -> None:
    workspace = _create_workspace(tmp_path)
    plugins_dir = workspace.root / "plugins"
    plugins_dir.mkdir()
    _install_plugin(workspace)

    manager = _build_manager(tmp_path, workspace)
    manager.register("core")
    manager.load_plugins()

    entry = manager.registry.resolve("mcp:serve")
    assert entry.group == "mcp"
    assert entry.origin == "mcp"


def test_mcp_command_invoke_runs_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _create_workspace(tmp_path)
    plugins_dir = workspace.root / "plugins"
    plugins_dir.mkdir()
    _install_plugin(workspace)

    manager = _build_manager(tmp_path, workspace)
    manager.register("core")
    manager.load_plugins()

    entry = manager.registry.resolve("mcp:serve")
    assert entry.origin == "mcp"

    import importlib

    server_module = importlib.import_module("cpm_mcp_plugin.server")
    run_log: list[str] = []

    def fake_run() -> None:
        run_log.append("ran")

    monkeypatch.setattr(server_module.mcp, "run", fake_run)

    command = entry.target()
    namespace = argparse.Namespace(cpm_dir=".cpm", embed_url=None)
    assert command.run(namespace) == 0
    assert run_log == ["ran"]
