"""Simple event bus used by the CPM core services."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, DefaultDict

__all__ = ["Event", "EventHandler", "EventBus", "STANDARD_EVENTS"]

STANDARD_EVENTS = (
    "pre_discovery",
    "post_discovery",
    "pre_plugin_init",
    "post_plugin_init",
    "ready",
    "shutdown",
)


@dataclass(frozen=True)
class Event:
    """Lightweight event descriptor."""

    name: str
    payload: dict[str, Any]


EventHandler = Callable[[Event], None]


@dataclass(frozen=True)
class _EventSubscription:
    priority: int
    order: int
    handler: EventHandler


class EventBus:
    """Synchronous event bus with deterministic delivery."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[str, list[_EventSubscription]] = defaultdict(list)
        self._sequence: DefaultDict[str, int] = defaultdict(int)

    # kept for backwards compatibility with existing code
    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self.on(event_name, handler)

    def on(self, event_name: str, handler: EventHandler, priority: int = 0) -> None:
        """Register a handler for `event_name` with optional priority."""
        order = self._sequence[event_name]
        self._sequence[event_name] = order + 1
        self._handlers[event_name].append(
            _EventSubscription(priority=priority, order=order, handler=handler)
        )

    def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        event = Event(event_name, payload)
        subscriptions = sorted(
            self._handlers[event_name],
            key=lambda item: (-item.priority, item.order),
        )
        for subscription in subscriptions:
            subscription.handler(event)
