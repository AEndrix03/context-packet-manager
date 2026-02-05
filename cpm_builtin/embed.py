"""High-level helpers for the CPM embed CLI surface."""

from __future__ import annotations

from cpm_builtin.embeddings import EmbeddingsConfigService


def start_embed() -> str:
    """Return a quick status string about the configured embedding provider."""

    service = EmbeddingsConfigService()
    default = service.default_provider()
    if default:
        return f"default embedding provider is '{default.name}' ({default.url})"
    return "no embedding providers configured; use `cpm embed add`"
