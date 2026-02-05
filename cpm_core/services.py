"""Service container that lazily instantiates CPM components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Set

__all__ = ["ServiceContainer"]

ServiceProvider = Callable[["ServiceContainer"], Any]


@dataclass(frozen=True)
class _ServiceRegistration:
    provider: ServiceProvider
    singleton: bool


class ServiceContainer:
    """Simple dependency container with lazy initialization."""

    def __init__(self) -> None:
        self._registrations: Dict[str, _ServiceRegistration] = {}
        self._singletons: Dict[str, Any] = {}
        self._initializing: Set[str] = set()

    def register(
        self,
        name: str,
        provider: ServiceProvider,
        *,
        singleton: bool = True,
    ) -> None:
        """Register a provider that will be invoked lazily."""
        if name in self._registrations:
            raise ValueError(f"service {name!r} already registered")
        self._registrations[name] = _ServiceRegistration(provider=provider, singleton=singleton)

    def get(self, name: str) -> Any:
        """Resolve `name`, instantiating it only when first requested."""
        registration = self._registrations.get(name)
        if registration is None:
            raise KeyError(f"service {name!r} is not registered")

        if registration.singleton and name in self._singletons:
            return self._singletons[name]

        if name in self._initializing:
            raise RuntimeError(f"re-entrant initialization detected for {name!r}")

        self._initializing.add(name)
        try:
            instance = registration.provider(self)
        finally:
            self._initializing.remove(name)

        if registration.singleton:
            self._singletons[name] = instance

        return instance
