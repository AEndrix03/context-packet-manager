"""Helper utilities for storing CPM workspace configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

DEFAULT_APP_NAME = "cpm"
CONFIG_FILE_NAME = "config.toml"


def default_config_path() -> Path:
    """Return the platform-specific default config path for the CPM workspace."""

    base_dir = Path(user_config_dir(DEFAULT_APP_NAME, appauthor=False))
    return base_dir / CONFIG_FILE_NAME


@dataclass
class ConfigStore:
    path: Path = field(default_factory=default_config_path)
    _store: dict[str, Any] = field(default_factory=dict, init=False)

    def get(self, key: str, default: Any | None = None) -> Any | None:
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value
