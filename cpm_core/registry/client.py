"""Very light registry client for the CPM prototype."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegistryClient:
    """Simple fake client that tracks a mocked endpoint."""

    endpoint: str = "https://registry.local"
    status: str = "disconnected"

    def ping(self) -> str:
        self.status = "online"
        return self.status
