"""Unit tests for the CPM core ServiceContainer."""

from __future__ import annotations

import pytest

from cpm_core.services import ServiceContainer


def test_service_registration_respects_singleton_vs_factory() -> None:
    container = ServiceContainer()
    counters = {"singleton": 0, "factory": 0}

    def singleton_provider(_: ServiceContainer):
        counters["singleton"] += 1
        return object()

    def factory_provider(_: ServiceContainer):
        counters["factory"] += 1
        return {"call": counters["factory"]}

    container.register("singleton", singleton_provider)
    container.register("factory", factory_provider, singleton=False)

    first_singleton = container.get("singleton")
    assert first_singleton is container.get("singleton")
    assert counters["singleton"] == 1

    first_factory = container.get("factory")
    second_factory = container.get("factory")
    assert first_factory is not second_factory
    assert counters["factory"] == 2


def test_lazy_initialization_waits_for_get() -> None:
    called = False

    def provider(_: ServiceContainer):
        nonlocal called
        called = True
        return "ready"

    container = ServiceContainer()
    container.register("lazy", provider)

    assert not called
    assert container.get("lazy") == "ready"
    assert called


def test_reentrant_initialization_raises() -> None:
    container = ServiceContainer()

    def provider(c: ServiceContainer):
        return c.get("reentrant")

    container.register("reentrant", provider)
    with pytest.raises(RuntimeError):
        container.get("reentrant")


def test_get_unregistered_service_errors() -> None:
    container = ServiceContainer()
    with pytest.raises(KeyError):
        container.get("missing")
