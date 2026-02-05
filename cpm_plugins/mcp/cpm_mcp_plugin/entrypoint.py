"""Entrypoint that wires MCP tooling modules into the plugin system."""

from __future__ import annotations

from . import features, server


class MCPEntrypoint:
    """Initialize the MCP plugin by loading feature modules."""

    def init(self, ctx) -> None:  # noqa: ARG001
        self.context = ctx
        _ = features.MCPServeCommand
        _ = server  # ensure the FastMCP tools are registered
