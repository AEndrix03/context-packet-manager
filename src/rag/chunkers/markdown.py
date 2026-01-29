from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..schema import Chunk
from .base import ChunkingConfig
from .token_budget import TokenBudgeter, Block

try:
    import mistune  # type: ignore
except Exception:  # pragma: no cover
    mistune = None  # type: ignore


def _plain_text_from_md_ast(node) -> str:
    if node is None:
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("raw", "") or node.get("text", "")
    if t == "paragraph":
        return "".join(_plain_text_from_md_ast(ch) for ch in node.get("children", []))
    if t == "heading":
        level = node.get("level", 1)
        inner = "".join(_plain_text_from_md_ast(ch) for ch in node.get("children", []))
        return f"{'#' * level} {inner}".strip()
    if t == "block_code":
        info = node.get("info", "") or ""
        code = node.get("raw", "") or ""
        fence = "```" + info.strip()
        return f"{fence}\n{code}\n```".strip()
    if t == "list":
        items = []
        for it in node.get("children", []):
            items.append("- " + _plain_text_from_md_ast(it))
        return "\n".join(items)
    if t == "list_item":
        return "".join(_plain_text_from_md_ast(ch) for ch in node.get("children", []))
    return "".join(_plain_text_from_md_ast(ch) for ch in node.get("children", []))


def _split_markdown_sections(text: str) -> List[Tuple[str, str]]:
    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    cur_title = ""
    cur: List[str] = []
    for line in lines:
        if line.startswith("#"):
            if cur:
                sections.append((cur_title, cur))
            cur_title = line.strip()
            cur = [line]
        else:
            cur.append(line)
    if cur:
        sections.append((cur_title, cur))
    return [(t, "\n".join(s).strip()) for t, s in sections if "\n".join(s).strip()]


@dataclass
class MarkdownChunker:
    name: str = "markdown"

    def __init__(self, token_budgeter: Optional[TokenBudgeter] = None):
        self.budgeter = token_budgeter or TokenBudgeter()

    def chunk(
        self,
        text: str,
        source_id: str,
        *,
        ext: str,
        config: ChunkingConfig,
        **kwargs: Any,
    ) -> List[Chunk]:
        blocks: List[Block] = []

        sections: List[Tuple[str, str]] = []
        if mistune is not None:
            try:
                md = mistune.create_markdown(renderer="ast")
                ast_nodes = md(text)
                # treat each top-level node as a "section-like" parent
                for i, n in enumerate(ast_nodes):
                    plain = _plain_text_from_md_ast(n).strip()
                    if plain:
                        title = n.get("type") or "node"
                        sections.append((f"{title}:{i}", plain))
            except Exception:
                sections = []

        if not sections:
            sections = _split_markdown_sections(text)

        if not sections and text.strip():
            sections = [("doc", text.strip())]

        for i, (title, sec_text) in enumerate(sections):
            parent_id = f"{source_id}:md:section:{i}:{(title or 'untitled')[:64]}"
            parent_meta = {"kind": "md_section", "title": title, "lang": "markdown", "level": config.parent_level_name, "parent_id": parent_id}

            if config.emit_parent_chunks:
                blocks.append(Block(sec_text, dict(parent_meta)))

            if config.hierarchical:
                parts = self.budgeter.split_text_micro(
                    sec_text,
                    target_tokens=config.micro_chunk_tokens,
                    overlap_tokens=config.micro_overlap_tokens,
                    hard_cap_tokens=config.micro_hard_cap_tokens or config.hard_cap_tokens,
                    strategy="paragraphs",
                )
            else:
                parts = [sec_text]

            for j, p in enumerate(parts):
                child_meta = dict(parent_meta)
                child_meta["kind"] = "md_child"
                child_meta["level"] = config.child_level_name
                child_meta["parent_id"] = parent_id
                child_meta["child_index"] = j
                blocks.append(Block(p, child_meta))

        base_meta: Dict[str, Any] = {"source_id": source_id, "ext": ext, "lang": "markdown", "chunker": self.name}
        return self.budgeter.pack_blocks(
            blocks,
            source_id=source_id,
            base_meta=base_meta,
            chunk_tokens=config.chunk_tokens,
            overlap_tokens=config.overlap_tokens,
            hard_cap_tokens=config.hard_cap_tokens,
            chunk_id_prefix=self.name,
        )
