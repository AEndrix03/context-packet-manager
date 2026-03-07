"""Implementation of the MCP tooling surface backed by remote-first wrappers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from .env import apply_settings_to_env, load_settings
from .remote import evidence_digest as evidence_digest_impl
from .remote import lookup_remote
from .remote import plan_from_intent as plan_from_intent_impl
from .remote import query_remote

mcp = FastMCP(name="context-packet-manager")


@mcp.tool()
def lookup(
    name: str,
    version: str | None = None,
    alias: str | None = "latest",
    entrypoint: str | None = None,
    kind: str | None = None,
    capability: str | list[str] | None = None,
    os_name: str | None = None,
    arch: str | None = None,
    registry: str | None = None,
    ref: str | None = None,
    k: int = 3,
    cpm_root: str | None = None,
) -> Dict[str, Any]:
    """Resolve packet metadata only.

    Use this when the user asks to discover/select a packet or inspect metadata
    (version, alias, capabilities, entrypoints, kind, compatibility).
    Do not use `query` for metadata-only requests.
    """
    return lookup_remote(
        name=name,
        version=version,
        alias=alias,
        entrypoint=entrypoint,
        kind=kind,
        capability=capability,
        os_name=os_name,
        arch=arch,
        registry=registry,
        ref=ref,
        k=k,
        cpm_root=cpm_root,
    )


@mcp.tool()
def query(
    ref: str,
    q: str,
    k: int = 5,
    rerank: bool = True,
    registry: str | None = None,
    cpm_root: str | None = None,
) -> Dict[str, Any]:
    """Retrieve semantic evidence snippets from a packet.

    Use this only when the user asks a content question and you need snippets.
    Prefer passing a digest-pinned `ref` from `lookup.selected.pinned_uri`.
    Do not use this for packet discovery/version/capability lookup.
    Set `rerank=False` to skip cross-encoder reranking (faster, lower quality).
    """
    return query_remote(ref=ref, q=q, k=k, rerank=rerank, registry=registry, cpm_root=cpm_root)


@mcp.tool()
def plan_from_intent(
    intent: str,
    constraints: Optional[dict[str, Any]] = None,
    name_hint: str | None = None,
    version: str | None = None,
    registry: str | None = None,
    cpm_root: str | None = None,
) -> Dict[str, Any]:
    """Build a deterministic tool plan from user intent.

    The planner returns `intent_mode`:
    - `lookup` for metadata/discovery intents
    - `query` for semantic evidence intents
    """
    return plan_from_intent_impl(
        intent=intent,
        constraints=constraints or {},
        name_hint=name_hint,
        version=version,
        registry=registry,
        cpm_root=cpm_root,
    )


@mcp.tool()
def evidence_digest(
    ref: str,
    question: str,
    k: int = 6,
    max_chars: int = 1200,
    registry: str | None = None,
    cpm_root: str | None = None,
) -> Dict[str, Any]:
    """Compact and deduplicate `query` evidence for LLM context windows.

    Use after `query` when token budget is tight.
    """
    return evidence_digest_impl(
        ref=ref,
        question=question,
        k=k,
        max_chars=max_chars,
        registry=registry,
        cpm_root=cpm_root,
    )


def run_server(
    *,
    cpm_root: str | None = None,
    registry: str | None = None,
    embedding_url: str | None = None,
    embedding_model: str | None = None,
) -> None:
    settings = load_settings(
        cpm_root=cpm_root,
        registry=registry,
        embedding_url=embedding_url,
        embedding_model=embedding_model,
    )
    apply_settings_to_env(settings)
    mcp.run()
