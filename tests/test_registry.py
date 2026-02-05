"""Unit tests for the CPM feature registry utilities."""

from __future__ import annotations

import pytest

from cpm_core.registry import (
    AmbiguousFeatureError,
    CPMRegistryEntry,
    FeatureCollisionError,
    FeatureRegistry,
)


class _DummyFeature:
    """Placeholder target used for registry entries."""


def _entry(
    name: str,
    group: str,
    *,
    kind: str = "command",
    origin: str = "core",
) -> CPMRegistryEntry:
    return CPMRegistryEntry(
        group=group,
        name=name,
        target=_DummyFeature,
        kind=kind,
        origin=origin,
    )


def test_register_collision_qualified() -> None:
    registry = FeatureRegistry()
    entry = _entry("deploy", "core")

    registry.register(entry)
    with pytest.raises(FeatureCollisionError):
        registry.register(entry)


def test_resolve_ambiguous_name_requires_qualification() -> None:
    registry = FeatureRegistry()
    core_entry = _entry("sync", "core")
    plugin_entry = _entry("sync", "plugin")

    registry.register(core_entry)
    registry.register(plugin_entry)

    with pytest.raises(AmbiguousFeatureError) as excinfo:
        registry.resolve("sync")

    assert excinfo.value.candidates == tuple(
        sorted(e.qualified_name for e in (core_entry, plugin_entry))
    )
    assert registry.resolve(core_entry.qualified_name) is core_entry
    assert registry.resolve(plugin_entry.qualified_name) is plugin_entry


def test_resolve_name_when_unique() -> None:
    registry = FeatureRegistry()
    entry = _entry("deploy", "core")

    registry.register(entry)

    assert registry.resolve("deploy") is entry
    assert registry.resolve(entry.qualified_name) is entry


def test_display_names_shows_qualified_when_needed() -> None:
    registry = FeatureRegistry()
    unique_entry = _entry("deploy", "core")
    conflict_core = _entry("sync", "core")
    conflict_plugin = _entry("sync", "plugin")

    registry.register(unique_entry)
    registry.register(conflict_core)
    registry.register(conflict_plugin)

    assert registry.display_names() == (
        "deploy",
        conflict_core.qualified_name,
        conflict_plugin.qualified_name,
    )
