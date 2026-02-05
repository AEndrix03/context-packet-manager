"\"\"\"Platform-independent helpers for CPM paths.\"\"\""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

_DEFAULT_APP_NAME = "cpm"
_DEFAULT_APP_AUTHOR = "Component RAG"


@dataclass(frozen=True)
class UserDirs:
    """Expose the platform-configured locations for config/cache/data trees."""

    app_name: str = _DEFAULT_APP_NAME
    app_author: str = _DEFAULT_APP_AUTHOR
    config_dir_override: Path | None = None
    cache_dir_override: Path | None = None
    data_dir_override: Path | None = None

    def config_dir(self) -> Path:
        return (
            self.config_dir_override
            if self.config_dir_override
            else Path(user_config_dir(self.app_name, appauthor=self.app_author))
        )

    def cache_dir(self) -> Path:
        return (
            self.cache_dir_override
            if self.cache_dir_override
            else Path(user_cache_dir(self.app_name, appauthor=self.app_author))
        )

    def data_dir(self) -> Path:
        return (
            self.data_dir_override
            if self.data_dir_override
            else Path(user_data_dir(self.app_name, appauthor=self.app_author))
        )
