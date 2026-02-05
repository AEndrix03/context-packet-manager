"""Entrypoint for the user override fixture."""

from __future__ import annotations

from . import features


class OverrideEntrypoint:
    def init(self, ctx) -> None:
        _ = features.UserCommand
