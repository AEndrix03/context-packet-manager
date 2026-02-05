"""Features that register as sample command + builder."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Sequence

from cpm_core.api.abc import CPMAbstractBuilder, CPMAbstractCommand
from cpm_core.api.decorators import cpmcommand, cpmbuilder


@cpmcommand(name="sample-command")
class SampleCommand(CPMAbstractCommand):
    """Command published by the sample plugin."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--sample", action="store_true")

    def run(self, argv: Sequence[str]) -> int:
        self.args = argv
        return 0


@cpmbuilder(name="sample-builder")
class SampleBuilder(CPMAbstractBuilder):
    """Builder published by the sample plugin."""

    def build(self, source: str, *, destination: str | None = None) -> None:
        self.source = source
        self.destination = destination
