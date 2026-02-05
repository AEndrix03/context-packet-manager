"""Plugin-related tests for the CPM core runtime."""

from pathlib import Path

from cpm_core.events import EventBus
from cpm_core.paths import UserDirs
from cpm_core.plugin_manager import PluginManager
from cpm_core.workspace import Workspace


def test_plugin_manager_registers_once(tmp_path: Path) -> None:
    workspace_dir = tmp_path / ".cpm"
    workspace_dir.mkdir()
    config_path = workspace_dir / "config.toml"
    config_path.write_text("")

    manager = PluginManager(
        workspace=Workspace(root=workspace_dir, config_path=config_path),
        events=EventBus(),
        user_dirs=UserDirs(data_dir_override=tmp_path / "user_data"),
    )
    manager.register("alpha")
    manager.register("alpha")
    assert manager.list_plugins() == ("alpha",)
