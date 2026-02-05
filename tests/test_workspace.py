"""Tests for the CPM workspace resolver and layout helpers."""

from pathlib import Path

from cpm_core.paths import UserDirs
from cpm_core.workspace import (
    CONFIG_FILE_NAME,
    EMBEDDINGS_FILE_NAME,
    WorkspaceLayout,
    WorkspaceResolver,
)


def test_find_workspace_in_parent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace_root = project / ".cpm"
    workspace_root.mkdir(parents=True)
    (project / "sub").mkdir()

    resolver = WorkspaceResolver()
    found = resolver.find_workspace(project / "sub")
    assert found == workspace_root


def test_ensure_workspace_creates_layout(tmp_path: Path) -> None:
    resolver = WorkspaceResolver()
    start_dir = tmp_path / "project"
    start_dir.mkdir()

    workspace_root = resolver.ensure_workspace(start_dir)
    layout = WorkspaceLayout.from_root(workspace_root, CONFIG_FILE_NAME, EMBEDDINGS_FILE_NAME)

    assert layout.packages_dir.is_dir()
    assert layout.cache_dir.is_dir()
    assert layout.plugins_dir.is_dir()
    assert layout.state_dir.is_dir()
    assert layout.config_dir.is_dir()
    assert layout.logs_dir.is_dir()
    assert layout.embeddings_file.is_file()
    assert layout.config_file.is_file()

    second_root = resolver.ensure_workspace(start_dir)
    assert second_root == workspace_root


def test_ensure_workspace_handles_relative_paths(tmp_path: Path) -> None:
    resolver = WorkspaceResolver()
    nested = tmp_path / "project" / "nested"
    nested.mkdir(parents=True)
    relative_start = nested / ".." / "nested"

    workspace_root = resolver.ensure_workspace(relative_start)
    assert workspace_root == (nested.resolve() / ".cpm")


def test_config_resolution_precedence(tmp_path: Path) -> None:
    user_config_dir = tmp_path / "user-config"
    user_dirs = UserDirs(config_dir_override=user_config_dir)
    user_config_dir.mkdir()
    (user_config_dir / CONFIG_FILE_NAME).write_text('test_key = "user"')

    project = tmp_path / "project"
    workspace_dir = project / ".cpm"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / CONFIG_FILE_NAME).write_text('test_key = "workspace"')

    defaults = {"test_key": "default"}
    resolver = WorkspaceResolver(
        cli_overrides={"test_key": "cli"},
        env={"test_key": "env"},
        user_dirs=user_dirs,
        defaults=defaults,
    )
    assert resolver.resolve_setting("test_key", start_dir=project) == "cli"

    resolver = WorkspaceResolver(
        cli_overrides={},
        env={"test_key": "env"},
        user_dirs=user_dirs,
        defaults=defaults,
    )
    assert resolver.resolve_setting("test_key", start_dir=project) == "env"

    resolver = WorkspaceResolver(
        cli_overrides={},
        env={},
        user_dirs=user_dirs,
        defaults=defaults,
    )
    assert resolver.resolve_setting("test_key", start_dir=project) == "workspace"

    (workspace_dir / CONFIG_FILE_NAME).unlink()
    assert resolver.resolve_setting("test_key", start_dir=project) == "user"

    (user_config_dir / CONFIG_FILE_NAME).unlink()
    assert resolver.resolve_setting("test_key", start_dir=project) == "default"
