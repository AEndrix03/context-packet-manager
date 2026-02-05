"""Handle plugin manifest parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .errors import PluginManifestError


@dataclass(frozen=True)
class PluginManifest:
    """Immutable representation of a plugin manifest document."""

    id: str
    name: str
    version: str
    group: str
    entrypoint: str
    requires_cpm: str

    @staticmethod
    def _normalize_field(label: str, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise PluginManifestError(f"{label} cannot be empty.")
        return normalized

    @classmethod
    def load(cls, path: Path) -> "PluginManifest":
        """Load and validate plugin manifest data from ``plugin.toml``."""

        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise PluginManifestError(f"unable to read manifest at {path}") from exc

        plugin_section = document.get("plugin")
        if not isinstance(plugin_section, dict):
            raise PluginManifestError("missing or malformed [plugin] section")

        fields: dict[str, str] = {}
        for key in (
            "id",
            "name",
            "version",
            "group",
            "entrypoint",
            "requires_cpm",
        ):
            raw_value = plugin_section.get(key)
            if raw_value is None:
                raise PluginManifestError(f"missing '{key}' in manifest")
            if not isinstance(raw_value, str):
                raise PluginManifestError(f"'{key}' must be a string")
            fields[key] = cls._normalize_field(key, raw_value)

        return cls(**fields)
