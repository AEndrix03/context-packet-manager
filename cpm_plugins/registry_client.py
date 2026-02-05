"""Optional registry client plugin for CPM vNext."""


class RegistryPlugin:
    """Stub plugin that mirrors the registry client responsibilities."""

    name = "cpm-registry-client"

    def connect(self) -> str:
        return f"{self.name} connected to placeholder endpoint"
