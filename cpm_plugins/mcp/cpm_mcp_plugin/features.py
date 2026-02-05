"""Feature classes that expose the MCP server command."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Sequence

from cpm_core.api import CPMAbstractCommand, cpmcommand

from .server import run_server


@cpmcommand(name="serve")
class MCPServeCommand(CPMAbstractCommand):
    """Start the Model Context Protocol (MCP) server for CPM packets."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--cpm-dir",
            default=".cpm",
            help="Workspace root where context packets are installed.",
        )
        parser.add_argument(
            "--embed-url",
            help="Embedding server URL to expose to MCP clients.",
        )

    def run(self, argv: Sequence[str]) -> int:
        cpm_dir = getattr(argv, "cpm_dir", ".cpm")
        embed_url = getattr(argv, "embed_url", None)
        run_server(cpm_dir=cpm_dir, embed_url=embed_url)
        return 0
