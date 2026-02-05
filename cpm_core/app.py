"""Lightweight application workspace that wires together CPM core services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from cpm_core.builtins import (
    register_builtin_builders,
    register_builtin_commands,
)
from cpm_core.config import ConfigStore
from cpm_core.events import EventBus
from cpm_core.plugin_manager import PluginManager
from cpm_core.registry import FeatureRegistry, RegistryClient
from cpm_core.services import ServiceContainer
from cpm_core.workspace import Workspace, WorkspaceLayout, WorkspaceResolver
from cpm_core.paths import UserDirs


ServiceProvider = Callable[[ServiceContainer], Any]


@dataclass(frozen=True)
class CPMAppStatus:
    workspace: Workspace
    plugins: Sequence[str]
    commands: Sequence[str]
    registry_status: str


class CPMApp:
    """Entry point that glues the workspace, builtins, registry, and plugins."""

    def __init__(
        self,
        *,
        start_dir: Path | str | None = None,
        user_dirs: UserDirs | None = None,
        logger: logging.Logger | None = None,
        container: ServiceContainer | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("cpm_core.app")
        self.user_dirs = user_dirs or UserDirs()
        self.container = container or ServiceContainer()
        self.workspace_resolver = WorkspaceResolver(user_dirs=self.user_dirs)
        normalized_start = Path(start_dir) if isinstance(start_dir, str) else start_dir
        workspace_root = self.workspace_resolver.ensure_workspace(normalized_start)
        layout = WorkspaceLayout.from_root(
            workspace_root,
            self.workspace_resolver.config_filename,
            self.workspace_resolver.embeddings_filename,
        )
        layout.ensure()
        self.workspace = Workspace(root=workspace_root, config_path=layout.config_file)
        self.config = ConfigStore(path=self.workspace.config_path)
        self.events = EventBus()
        self.feature_registry = FeatureRegistry()
        self.plugin_manager = PluginManager(
            workspace=self.workspace,
            events=self.events,
            user_dirs=self.user_dirs,
            registry=self.feature_registry,
        )
        self.registry = RegistryClient()
        self._builtins_registered = False
        self._register_services()

    def _register_services(self) -> None:
        self._register_service("workspace", lambda _: self.workspace)
        self._register_service("config_store", lambda _: self.config)
        self._register_service("events", lambda _: self.events)
        self._register_service("feature_registry", lambda _: self.feature_registry)
        self._register_service("registry_client", lambda _: self.registry)
        self._register_service("plugin_manager", lambda _: self.plugin_manager)

    def _register_service(
        self,
        name: str,
        provider: ServiceProvider,
        *,
        singleton: bool = True,
    ) -> None:
        try:
            self.container.register(name, provider, singleton=singleton)
        except ValueError:
            self.logger.debug("service %s already registered, skipping", name)

    def _register_builtins(self) -> None:
        if self._builtins_registered:
            return
        register_builtin_commands(self.feature_registry)
        register_builtin_builders(self.feature_registry)
        self._builtins_registered = True

    def bootstrap(self) -> CPMAppStatus:
        self.plugin_manager.register("core")
        self._register_builtins()
        self.plugin_manager.load_plugins()
        self.events.emit("bootstrap", {})
        registry_status = self.registry.ping()
        return CPMAppStatus(
            workspace=self.workspace,
            plugins=self.plugin_manager.list_plugins(),
            commands=self.feature_registry.display_names(),
            registry_status=registry_status,
        )

    def status(self) -> dict[str, str]:
        plugins = ", ".join(self.plugin_manager.list_plugins()) or "none"
        commands = ", ".join(self.feature_registry.display_names()) or "none"
        return {
            "workspace_root": str(self.workspace.root),
            "workspace_config": str(self.workspace.config_path),
            "plugins": plugins,
            "commands": commands,
            "registry": self.registry.status,
        }
