"""Custom errors raised by the CPM feature registry."""

from __future__ import annotations

from typing import Sequence


class FeatureRegistryError(Exception):
    """Base class for feature registry errors."""


class FeatureCollisionError(FeatureRegistryError):
    """Raised when an entry already exists for a qualified name."""


class FeatureNotFoundError(FeatureRegistryError):
    """Raised when a feature cannot be resolved."""


class AmbiguousFeatureError(FeatureRegistryError):
    """Raised when multiple entries share the same simple name."""

    def __init__(self, name: str, candidates: Sequence[str]) -> None:
        message = f"{name!r} matches multiple entries: {', '.join(candidates)}"
        super().__init__(message)
        self.name = name
        self.candidates = tuple(candidates)
