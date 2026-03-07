"""Registry entry descriptor exposing qualified feature metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Type

VALID_KINDS: frozenset[str] = frozenset({"builder", "retriever", "command", "reranker", "indexer"})


@dataclass(frozen=True)
class CPMRegistryEntry:
    """Immutable descriptor for a registered CPM feature."""

    group: str
    name: str
    target: Type[Any]
    kind: str
    origin: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "group", self._validate_component("group", self.group))
        object.__setattr__(self, "name", self._validate_component("name", self.name))
        object.__setattr__(self, "kind", self._validate_component("kind", self.kind))
        object.__setattr__(self, "origin", self._validate_component("origin", self.origin))
        if self.kind not in VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}, got '{self.kind}'.")
        if not isinstance(self.target, type):
            raise TypeError("target must be a class type.")

    @staticmethod
    def _validate_component(label: str, value: str) -> str:
        if not value:
            raise ValueError(f"{label} cannot be empty.")
        if ":" in value:
            raise ValueError(f"{label} may not contain ':'.")
        return value

    @property
    def qualified_name(self) -> str:
        """Return the ``group:name`` identifier for this entry."""

        return f"{self.group}:{self.name}"
