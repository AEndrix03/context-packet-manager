"""Core CPM plugin support."""

from .context import PluginContext
from .errors import (
    PluginDiscoveryError,
    PluginError,
    PluginLoadError,
    PluginManifestError,
)
from .manager import PluginManager, PluginRecord, PluginState
from .manifest import PluginManifest

__all__ = [
    "PluginContext",
    "PluginManager",
    "PluginManifest",
    "PluginRecord",
    "PluginState",
    "PluginError",
    "PluginDiscoveryError",
    "PluginLoadError",
    "PluginManifestError",
]
