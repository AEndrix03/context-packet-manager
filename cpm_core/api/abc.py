"""Abstract base classes for CPM features."""

from __future__ import annotations

from abc import ABC, abstractmethod
from argparse import ArgumentParser
from typing import Sequence


class CPMAbstractCommand(ABC):
    """Base interface for CPM commands."""

    @classmethod
    @abstractmethod
    def configure(cls, parser: ArgumentParser) -> None:
        """Let the command configure CLI arguments."""

    @abstractmethod
    def run(self, argv: Sequence[str]) -> int:
        """Execute the command with parsed arguments."""


class CPMAbstractBuilder(ABC):
    """Base interface for CPM builders."""

    @abstractmethod
    def build(self, source: str, *, destination: str | None = None) -> None:
        """Build artifacts starting from ``source`` into an optional destination."""


class CPMAbstractRetriever(ABC):
    """Base interface for CPM retrievers."""

    @abstractmethod
    def retrieve(self, identifier: str) -> str:
        """Retrieve a resource referenced by ``identifier``."""
