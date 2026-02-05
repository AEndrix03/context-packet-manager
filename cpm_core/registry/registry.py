"""In-memory registry for CPM features."""

from __future__ import annotations

from .entry import CPMRegistryEntry
from .errors import (
    AmbiguousFeatureError,
    FeatureCollisionError,
    FeatureNotFoundError,
)


class FeatureRegistry:
    """A registry that tracks features by qualified and simple names."""

    def __init__(self) -> None:
        self._by_qualified: dict[str, CPMRegistryEntry] = {}
        self._by_name: dict[str, list[CPMRegistryEntry]] = {}

    def register(self, entry: CPMRegistryEntry) -> None:
        """Register an entry, raising on qualified name collisions."""

        qualified = entry.qualified_name
        if qualified in self._by_qualified:
            raise FeatureCollisionError(f"{qualified} is already registered.")
        self._by_qualified[qualified] = entry
        self._by_name.setdefault(entry.name, []).append(entry)

    def resolve(self, name_or_qualified: str) -> CPMRegistryEntry:
        """Resolve either a simple name or a qualified ``group:name``."""

        if ":" in name_or_qualified:
            return self._resolve_qualified(name_or_qualified)
        return self._resolve_name(name_or_qualified)

    def _resolve_qualified(self, qualified: str) -> CPMRegistryEntry:
        entry = self._by_qualified.get(qualified)
        if entry is None:
            raise FeatureNotFoundError(f"{qualified} is not registered.")
        return entry

    def _resolve_name(self, name: str) -> CPMRegistryEntry:
        candidates = self._by_name.get(name)
        if not candidates:
            raise FeatureNotFoundError(f"{name} is not registered.")
        if len(candidates) > 1:
            sorted_candidates = sorted(entry.qualified_name for entry in candidates)
            raise AmbiguousFeatureError(name, sorted_candidates)
        return candidates[0]

    def display_names(self) -> tuple[str, ...]:
        """List feature names, showing ``group:name`` when ambiguous."""

        formatted: list[str] = []
        for name in sorted(self._by_name):
            candidates = self._by_name[name]
            if len(candidates) == 1:
                formatted.append(name)
                continue
            qualified = sorted(entry.qualified_name for entry in candidates)
            formatted.extend(qualified)
        return tuple(formatted)

    def entries(self) -> tuple[CPMRegistryEntry, ...]:
        """Return all registered entries in qualified order."""

        return tuple(sorted(self._by_qualified.values(), key=lambda entry: entry.qualified_name))
