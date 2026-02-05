"""Plugin discovery, loading, and registry integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence

from cpm_core.events import EventBus
from cpm_core.paths import UserDirs
from cpm_core.registry import (
    CPMRegistryEntry,
    FeatureCollisionError,
    FeatureRegistry,
)
from cpm_core.workspace import (
    CONFIG_FILE_NAME,
    EMBEDDINGS_FILE_NAME,
    Workspace,
    WorkspaceLayout,
)

from .context import PluginContext
from .errors import PluginLoadError, PluginManifestError
from .loader import PluginLoader
from .manifest import PluginManifest


PRE_DISCOVERY_EVENT = "plugin.pre_discovery"
POST_DISCOVERY_EVENT = "plugin.post_discovery"
PRE_PLUGIN_INIT_EVENT = "plugin.pre_plugin_init"
POST_PLUGIN_INIT_EVENT = "plugin.post_plugin_init"


class PluginState(Enum):
    """Lifecycle states for plugins."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass
class PluginRecord:
    """Snapshot of a plugin that has been discovered."""

    id: str
    manifest: PluginManifest | None = None
    path: Path | None = None
    state: PluginState = PluginState.PENDING
    source: str = "unknown"
    features: tuple[CPMRegistryEntry, ...] = field(default_factory=tuple)
    error: str | None = None


@dataclass(frozen=True)
class _PluginCandidate:
    id: str
    manifest: PluginManifest
    path: Path
    source: str


class PluginManager:
    """Manage plugin discovery, initialization, and feature registration."""

    def __init__(
        self,
        workspace: Workspace,
        events: EventBus,
        *,
        user_dirs: UserDirs | None = None,
        registry: FeatureRegistry | None = None,
    ) -> None:
        self.workspace = workspace
        self.events = events
        self.user_dirs = user_dirs or UserDirs()
        self.registry = registry or FeatureRegistry()
        self._logger = logging.getLogger(__name__)
        layout = WorkspaceLayout.from_root(
            self.workspace.root,
            CONFIG_FILE_NAME,
            EMBEDDINGS_FILE_NAME,
        )
        self._workspace_plugins_dir = layout.plugins_dir
        self._workspace_plugins_dir.mkdir(parents=True, exist_ok=True)
        self._user_plugins_dir = self.user_dirs.data_dir() / "plugins"
        self._registered: list[str] = []
        self._records: dict[str, PluginRecord] = {}
        self._loaded = False

    def register(self, name: str, *, state: PluginState | None = PluginState.READY) -> None:
        """Register plugin identifiers (used by builtins)."""

        if name not in self._registered:
            self._registered.append(name)
        record = self._records.get(name)
        if record is None:
            self._records[name] = PluginRecord(
                id=name,
                state=state or PluginState.READY,
                source="builtin",
            )
            return
        if state is not None and record.state == PluginState.PENDING:
            record.state = state

    def list_plugins(self) -> tuple[str, ...]:
        return tuple(self._registered)

    def plugin_records(self) -> tuple[PluginRecord, ...]:
        return tuple(
            self._records[name]
            for name in self._registered
            if name in self._records
        )

    def load_plugins(self) -> None:
        """Discover and load plugins from workspace/user paths."""

        if self._loaded:
            return

        workspace_path = str(self._workspace_plugins_dir)
        user_path = str(self._user_plugins_dir)
        self.events.emit(
            PRE_DISCOVERY_EVENT,
            {"workspace_plugins": workspace_path, "user_plugins": user_path},
        )

        candidates = self._discover_candidates()

        self.events.emit(
            POST_DISCOVERY_EVENT,
            {"plugins": [candidate.id for candidate in candidates]},
        )

        for candidate in candidates:
            context = self._prepare_candidate(candidate)
            record = self._records[candidate.id]
            self.events.emit(
                PRE_PLUGIN_INIT_EVENT,
                {"plugin_id": candidate.id, "source": candidate.source},
            )

            registered_entries: list[CPMRegistryEntry] = []
            try:
                loader = PluginLoader(candidate.manifest, context)
                entries = loader.load()
                for entry in entries:
                    self.registry.register(entry)
                    registered_entries.append(entry)
            except PluginLoadError as exc:
                record.state = PluginState.FAILED
                record.error = str(exc)
                self._logger.exception("plugin %s failed to load", candidate.id)
            except FeatureCollisionError as exc:
                record.state = PluginState.FAILED
                record.error = str(exc)
                self._logger.error("feature collision while loading %s: %s", candidate.id, exc)
            else:
                record.state = PluginState.READY
                record.error = None
            finally:
                record.features = tuple(registered_entries)
                self.events.emit(
                    POST_PLUGIN_INIT_EVENT,
                    {
                        "plugin_id": candidate.id,
                        "state": record.state.value,
                        "error": record.error,
                    },
                )

        self._loaded = True

    def _discover_candidates(self) -> list[_PluginCandidate]:
        discovered: list[_PluginCandidate] = []
        seen: set[str] = set()

        directories: Sequence[tuple[str, Path]] = [
            ("workspace", self._workspace_plugins_dir),
            ("user", self._user_plugins_dir),
        ]

        for source, directory in directories:
            if not directory.exists():
                continue
            for child in sorted(directory.iterdir(), key=lambda path: path.name):
                if not child.is_dir():
                    continue
                manifest_path = child / "plugin.toml"
                if not manifest_path.is_file():
                    continue
                try:
                    manifest = PluginManifest.load(manifest_path)
                except PluginManifestError as exc:
                    self._logger.warning("skipping %s: %s", child, exc)
                    continue
                if manifest.id != child.name:
                    self._logger.warning(
                        "plugin folder %s id mismatch %s", child, manifest.id
                    )
                    continue
                if manifest.id in seen:
                    continue
                seen.add(manifest.id)
                discovered.append(
                    _PluginCandidate(
                        id=manifest.id,
                        manifest=manifest,
                        path=child,
                        source=source,
                    )
                )

        return discovered

    def _prepare_candidate(self, candidate: _PluginCandidate) -> PluginContext:
        self._records[candidate.id] = PluginRecord(
            id=candidate.id,
            manifest=candidate.manifest,
            path=candidate.path,
            source=candidate.source,
        )
        self.register(candidate.id, state=None)
        return PluginContext(
            manifest=candidate.manifest,
            plugin_root=candidate.path,
            workspace_root=self.workspace.root,
            registry=self.registry,
            events=self.events,
            logger=logging.getLogger(f"{__name__}.{candidate.id}"),
        )
