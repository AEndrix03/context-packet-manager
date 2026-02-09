"""Helper utilities for registering built-in CPM features."""

from __future__ import annotations

from typing import Sequence

from cpm_core.registry import CPMRegistryEntry, FeatureRegistry

from .build import BuildCommand, register_builtin_builders
from .commands import (
    HelpCommand,
    InitCommand,
    ListingCommand,
    PluginDoctorCommand,
    PluginListCommand,
)
from .pkg import PkgCommand
from .query import QueryCommand, register_builtin_retrievers
from .lookup import LookupCommand
from .embed import EmbedCommand

__all__ = [
    "register_builtin_commands",
    "register_builtin_builders",
    "register_builtin_retrievers",
]

_BUILTIN_FEATURES: Sequence[type] = (
    InitCommand,
    BuildCommand,
    QueryCommand,
    PluginListCommand,
    PluginDoctorCommand,
    PkgCommand,
    EmbedCommand,
    LookupCommand,
    HelpCommand,
    ListingCommand,
)


def register_builtin_commands(registry: FeatureRegistry) -> None:
    """Register the built-in CPM command classes with the supplied registry."""

    for feature in _BUILTIN_FEATURES:
        metadata = getattr(feature, "__cpm_feature__", None)
        if metadata is None:
            continue
        registry.register(
            CPMRegistryEntry(
                group=metadata["group"],
                name=str(metadata["name"]),
                target=feature,
                kind=str(metadata["kind"]),
                origin="builtin",
            )
        )
