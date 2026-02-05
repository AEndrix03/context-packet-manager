"""Core runtime pieces for the CPM vNext reference implementation."""

from .app import CPMApp
from .config import ConfigStore, default_config_path
from .events import Event, EventBus
from .plugin_manager import PluginManager
from .registry import RegistryClient
from .services import ServiceContainer
from .paths import UserDirs
from .workspace import Workspace, WorkspaceResolver, WorkspaceLayout

__all__ = [
    "CPMApp",
    "ConfigStore",
    "default_config_path",
    "Event",
    "EventBus",
    "ServiceContainer",
    "PluginManager",
    "RegistryClient",
    "Workspace",
    "WorkspaceResolver",
    "WorkspaceLayout",
    "UserDirs",
]
