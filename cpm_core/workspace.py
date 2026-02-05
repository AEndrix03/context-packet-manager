"""Workspace helpers that find or create the .cpm directory hierarchy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import tomllib

from .paths import UserDirs

DEFAULT_WORKSPACE_NAME = ".cpm"
CONFIG_FILE_NAME = "config.toml"
EMBEDDINGS_FILE_NAME = "embeddings.yml"

_DEFAULTS: dict[str, str] = {
    "cpm_dir": DEFAULT_WORKSPACE_NAME,
    "config_file": CONFIG_FILE_NAME,
    "embeddings_file": EMBEDDINGS_FILE_NAME,
}
_ENV_KEY_MAP: dict[str, str] = {
    "cpm_dir": "RAG_CPM_DIR",
    "config_file": "CPM_CONFIG",
    "embeddings_file": "CPM_EMBEDDINGS",
}


def _load_config_from_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {key: str(value) for key, value in data.items()}


@dataclass(frozen=True)
class WorkspaceLayout:
    """Defines the directory structure that .cpm should contain."""

    root: Path
    packages_dir: Path
    cache_dir: Path
    plugins_dir: Path
    state_dir: Path
    config_dir: Path
    logs_dir: Path
    config_file: Path
    embeddings_file: Path

    @classmethod
    def from_root(
        cls,
        root: Path,
        config_filename: str,
        embeddings_filename: str,
    ) -> "WorkspaceLayout":
        root = root.resolve()
        return cls(
            root=root,
            packages_dir=root / "packages",
            cache_dir=root / "cache",
            plugins_dir=root / "plugins",
            state_dir=root / "state",
            config_dir=root / "config",
            logs_dir=root / "logs",
            config_file=root / config_filename,
            embeddings_file=root / embeddings_filename,
        )

    def ensure(self) -> None:
        """Ensure every layout entry exists and embeddings/config files are present."""
        for directory in (
            self.root,
            self.packages_dir,
            self.cache_dir,
            self.plugins_dir,
            self.state_dir,
            self.config_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.embeddings_file.touch(exist_ok=True)
        self.config_file.touch(exist_ok=True)


@dataclass
class WorkspaceResolver:
    """Resolve and create CPM workspaces while honoring layered configuration."""

    workspace_name: str = DEFAULT_WORKSPACE_NAME
    config_filename: str = CONFIG_FILE_NAME
    embeddings_filename: str = EMBEDDINGS_FILE_NAME
    user_dirs: UserDirs | None = None
    cli_overrides: Mapping[str, str] | None = None
    env: Mapping[str, str] | None = None
    defaults: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        self.user_dirs = self.user_dirs or UserDirs()
        self.cli_overrides = dict(self.cli_overrides or {})
        self.env = self.env or os.environ
        base_defaults = dict(_DEFAULTS)
        if self.defaults:
            base_defaults.update(self.defaults)
        self.defaults = base_defaults

    # ---------- Public API ----------

    def find_workspace(self, start_dir: Path | None = None) -> Path | None:
        """Look for an existing .cpm workspace by walking parent directories."""
        override = self._override_root_value()
        if override:
            candidate = override.expanduser().resolve()
            if candidate.is_dir():
                return candidate
            return None
        start = (Path(start_dir) if start_dir else Path.cwd()).resolve()
        for current in (start, *start.parents):
            candidate = current / self.workspace_name
            if candidate.is_dir():
                return candidate
        return None

    def ensure_workspace(self, start_dir: Path | None = None) -> Path:
        """Create the minimal .cpm hierarchy and return the workspace root."""
        override = self._override_root_value()
        if override:
            root = override.expanduser().resolve()
        else:
            existing = self.find_workspace(start_dir)
            if existing is not None:
                root = existing
            else:
                base = (Path(start_dir) if start_dir else Path.cwd()).resolve()
                root = base / self.workspace_name
        layout = WorkspaceLayout.from_root(root, self.config_filename, self.embeddings_filename)
        layout.ensure()
        return layout.root

    def resolve_setting(self, key: str, start_dir: Path | None = None) -> str | None:
        """Return the value for `key` using CLI, env, workspace, user, defaults order."""
        if value := self.cli_overrides.get(key):
            return value
        if value := self._env_value(key):
            return value
        workspace_layer = self._workspace_config_layer(start_dir)
        if (value := workspace_layer.get(key)):
            return value
        user_layer = self._user_config_layer()
        if (value := user_layer.get(key)):
            return value
        return self.defaults.get(key)

    # ---------- Internal helpers ----------

    def _env_value(self, key: str) -> str | None:
        value = self.env.get(key)
        if value:
            return value
        alias = _ENV_KEY_MAP.get(key)
        if alias:
            return self.env.get(alias)
        return None

    def _override_root_value(self) -> Path | None:
        if override := self.cli_overrides.get("cpm_dir"):
            return Path(override)
        if override := self._env_value("cpm_dir"):
            return Path(override)
        return None

    def _workspace_config_layer(self, start_dir: Path | None) -> dict[str, str]:
        workspace_root = self.find_workspace(start_dir)
        if workspace_root is None:
            return {}
        return _load_config_from_file(workspace_root / self.config_filename)

    def _user_config_layer(self) -> dict[str, str]:
        config_path = self.user_dirs.config_dir() / self.config_filename
        return _load_config_from_file(config_path)


@dataclass(frozen=True)
class Workspace:
    """Thin descriptor for the root .cpm directory and configuration file."""

    root: Path
    config_path: Path

    @classmethod
    def find_workspace_root(cls, start: Path | None = None) -> "Workspace":
        resolver = WorkspaceResolver()
        root = resolver.find_workspace(start)
        if root is None:
            root = (Path(start) if start else Path.cwd()).resolve() / resolver.workspace_name
        layout = WorkspaceLayout.from_root(root, resolver.config_filename, resolver.embeddings_filename)
        return cls(root=root, config_path=layout.config_file)
