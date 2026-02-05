"""Load plugin entrypoints and tree-scan their feature classes."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from cpm_core.registry import CPMRegistryEntry

from .context import PluginContext
from .errors import PluginLoadError
from .manifest import PluginManifest


class PluginLoader:
    """Responsible for importing and initializing a single plugin."""

    def __init__(self, manifest: PluginManifest, context: PluginContext) -> None:
        self.manifest = manifest
        self.context = context
        self._module_path, self._attribute = self._split_entrypoint(manifest.entrypoint)
        self._prefixes = tuple(self._determine_prefixes())

    def load(self) -> tuple[CPMRegistryEntry, ...]:
        """Import, initialize and inspect plugin features."""

        try:
            with self._insert_sys_path():
                entry_cls = self._import_entry_class()
                entry_point = entry_cls()
                if not hasattr(entry_point, "init"):
                    raise PluginLoadError(
                        f"entrypoint {entry_cls.__name__} lacks an init() method"
                    )
                entry_point.init(self.context)
        except PluginLoadError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise PluginLoadError(
                f"plugin {self.manifest.id} failed to initialize: {exc}"
            ) from exc

        return self._scan_for_features()

    def _split_entrypoint(self, entrypoint: str) -> tuple[str, str]:
        if ":" in entrypoint:
            module_path, attribute = entrypoint.split(":", 1)
        elif "." in entrypoint:
            module_path, attribute = entrypoint.rsplit(".", 1)
        else:
            raise PluginLoadError(
                f"entrypoint for plugin {self.manifest.id} is not a module path"
            )

        if not module_path or not attribute:
            raise PluginLoadError(
                f"entrypoint for plugin {self.manifest.id} is incomplete"
            )
        return module_path, attribute

    @contextmanager
    def _insert_sys_path(self) -> Iterator[Path]:
        path = str(self.context.plugin_root)
        already_present = path in sys.path
        if not already_present:
            sys.path.insert(0, path)
        try:
            yield self.context.plugin_root
        finally:
            if not already_present and path in sys.path:
                sys.path.remove(path)

    def _import_entry_class(self) -> type:
        try:
            module = importlib.import_module(self._module_path)
        except ImportError as exc:
            raise PluginLoadError(
                f"unable to import module {self._module_path} for plugin {self.manifest.id}"
            ) from exc

        try:
            entry_cls = getattr(module, self._attribute)
        except AttributeError as exc:
            raise PluginLoadError(
                f"module {self._module_path} does not expose {self._attribute}"
            ) from exc

        if not isinstance(entry_cls, type):
            raise PluginLoadError(
                f"entrypoint {self._attribute} in {self._module_path} is not a class"
            )

        return entry_cls

    def _determine_prefixes(self) -> Iterable[str]:
        root = self._module_path.split(".", 1)[0]
        yield from (
            prefix
            for prefix in {root, self._module_path, self.manifest.id}
            if prefix
        )

    def _matches_module(self, module_name: str) -> bool:
        return any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in self._prefixes
        )

    def _scan_for_features(self) -> tuple[CPMRegistryEntry, ...]:
        results: list[CPMRegistryEntry] = []
        seen_targets: set[int] = set()

        for module_name, module in list(sys.modules.items()):
            if module is None or not self._matches_module(module_name):
                continue
            for candidate in vars(module).values():
                if not isinstance(candidate, type):
                    continue
                metadata = getattr(candidate, "__cpm_feature__", None)
                if metadata is None:
                    continue
                target_id = id(candidate)
                if target_id in seen_targets:
                    continue
                seen_targets.add(target_id)
                results.append(
                    CPMRegistryEntry(
                        group=self.manifest.group,
                        name=str(metadata["name"]),
                        target=candidate,
                        kind=str(metadata["kind"]),
                        origin=self.manifest.id,
                    )
                )

        return tuple(results)
