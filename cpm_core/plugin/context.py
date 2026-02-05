"""Runtime context shared with plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging

from cpm_core.events import EventBus
from cpm_core.registry import FeatureRegistry

from .manifest import PluginManifest


@dataclass(frozen=True)
class PluginContext:
    """Information surfaces to plugins when they initialize."""

    manifest: PluginManifest
    plugin_root: Path
    workspace_root: Path
    registry: FeatureRegistry
    events: EventBus
    logger: logging.Logger
