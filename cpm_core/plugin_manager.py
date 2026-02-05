"""Backwards-compatible shim that exposes the new plugin manager."""

from __future__ import annotations

from .plugin.manager import PluginManager

__all__ = ["PluginManager"]
