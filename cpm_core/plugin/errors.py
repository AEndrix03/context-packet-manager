"""Plugin-specific error types."""


class PluginError(Exception):
    """Base type for plugin-related failures."""


class PluginManifestError(PluginError):
    """Raised when the plugin manifest cannot be loaded or validated."""


class PluginDiscoveryError(PluginError):
    """Raised when plugin discovery cannot proceed."""


class PluginLoadError(PluginError):
    """Raised when a plugin entrypoint cannot be loaded or initialized."""
