"""User override command."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Sequence

from cpm_core.api.abc import CPMAbstractCommand
from cpm_core.api.decorators import cpmcommand


@cpmcommand(name="override-user")
class UserCommand(CPMAbstractCommand):
    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--user", action="store_true")

    def run(self, argv: Sequence[str]) -> int:
        self.argv = argv
        return 0
