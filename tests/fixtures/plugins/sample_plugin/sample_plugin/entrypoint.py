"""Entrypoint stub for the sample plugin fixture."""

from __future__ import annotations

from . import features


class PluginEntrypoint:
    """Dummy entrypoint that loads feature modules."""

    def init(self, ctx) -> None:
        self.context = ctx
        _ = features.SampleCommand
        _ = features.SampleBuilder
