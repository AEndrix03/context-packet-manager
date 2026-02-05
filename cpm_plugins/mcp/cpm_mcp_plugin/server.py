"""Implementation of the MCP tooling surface backed by packet helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from .reader import PacketReader
from .retriever import EmbedServerError, PacketRetriever

mcp = FastMCP(name="context-packet-manager")


def _resolve_cpm_dir(override: Optional[str]) -> Path:
    return Path(override or os.environ.get("RAG_CPM_DIR", ".cpm"))


@mcp.tool()
def lookup(
    cpm_dir: str | None = None,
    include_all_versions: bool = False,
) -> Dict[str, Any]:
    reader = PacketReader(_resolve_cpm_dir(cpm_dir))
    packets = reader.list_packets(include_all_versions=bool(include_all_versions))
    directory = reader.root.resolve()
    return {
        "ok": True,
        "cpm_dir": str(directory).replace("\\", "/"),
        "packets": packets,
        "count": len(packets),
    }


@mcp.tool()
def query(
    packet: str,
    query: str,
    k: int = 5,
    cpm_dir: str | None = None,
    embed_url: Optional[str] = None,
) -> Dict[str, Any]:
    root = _resolve_cpm_dir(cpm_dir)
    try:
        retriever = PacketRetriever(root, packet, embed_url=embed_url)
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "packet_not_found",
            "packet": packet,
            "tried": str(root / packet).replace("\\", "/"),
        }
    except EmbedServerError as exc:
        return {
            "ok": False,
            "error": "embed_server_unreachable",
            "embed_url": exc.embed_url,
            "hint": "start it with: rag cpm embed start-server --detach (or set RAG_EMBED_URL)",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "retrieval_failed",
            "detail": str(exc),
        }

    return retriever.retrieve(query, k)


def run_server(*, cpm_dir: str | None = None, embed_url: str | None = None) -> None:
    if cpm_dir:
        os.environ["RAG_CPM_DIR"] = cpm_dir
    if embed_url:
        os.environ["RAG_EMBED_URL"] = embed_url
    mcp.run()
