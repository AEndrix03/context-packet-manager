"""Unit tests for the CPM core EventBus."""

from cpm_core.events import EventBus, STANDARD_EVENTS


def test_event_handlers_run_in_priority_order() -> None:
    bus = EventBus()
    seen: list[str] = []

    def make_handler(label: str):
        def handler(event):
            seen.append(f"{label}:{event.payload['value']}")

        return handler

    bus.on("ready", make_handler("one"), priority=0)
    bus.on("ready", make_handler("two"), priority=0)
    bus.on("ready", make_handler("high"), priority=5)
    bus.on("ready", make_handler("low"), priority=-1)
    bus.emit("ready", {"value": "ok"})

    assert seen == ["high:ok", "one:ok", "two:ok", "low:ok"]


def test_subscribe_alias_uses_same_ordering() -> None:
    bus = EventBus()
    recorded: list[str] = []

    def handler(event):
        recorded.append(event.name)

    bus.subscribe("ready", handler)
    bus.emit("ready", {})
    assert recorded == ["ready"]


def test_standard_events_are_listed() -> None:
    assert STANDARD_EVENTS == (
        "pre_discovery",
        "post_discovery",
        "pre_plugin_init",
        "post_plugin_init",
        "ready",
        "shutdown",
    )
