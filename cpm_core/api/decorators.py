"""Decorators that mark CPM feature classes with metadata."""

from __future__ import annotations

from typing import Any, Callable, Type

from .abc import (
    CPMAbstractBuilder,
    CPMAbstractCommand,
    CPMAbstractRetriever,
)


_FeatureCandidate = Type[Any]


def _determine_group(cls: type, override: str | None) -> str:
    if override:
        return override
    module = getattr(cls, "__module__", "")
    parts = module.split(".")
    return parts[0] or "cpm"


def _attach_feature_metadata(
    cls: type, kind: str, *, name: str | None, group: str | None
) -> type:
    if not isinstance(cls, type):
        raise TypeError("Decorated object must be a class.")

    metadata = {
        "kind": kind,
        "name": name or cls.__name__,
        "group": _determine_group(cls, group),
    }
    metadata["qualified_name"] = f"{metadata['group']}:{metadata['name']}"
    setattr(cls, "__cpm_feature__", metadata)
    return cls


def _feature_decorator(
    base: type, kind: str
) -> Callable[[_FeatureCandidate | None], Callable[[_FeatureCandidate], _FeatureCandidate]]:
    def decorator(
        cls: _FeatureCandidate | None = None,
        *,
        name: str | None = None,
        group: str | None = None,
    ) -> Callable[[_FeatureCandidate], _FeatureCandidate] | _FeatureCandidate:
        def wrap(target: _FeatureCandidate) -> _FeatureCandidate:
            if not issubclass(target, base):
                raise TypeError(
                    f"{target.__name__} must subclass {base.__name__} to be registered as {kind}."
                )
            return _attach_feature_metadata(target, kind, name=name, group=group)

        if cls is None:
            return wrap
        return wrap(cls)

    return decorator


cpmcommand = _feature_decorator(CPMAbstractCommand, "command")
cpmbuilder = _feature_decorator(CPMAbstractBuilder, "builder")
cpmretriever = _feature_decorator(CPMAbstractRetriever, "retriever")
