from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.rag.schema import Chunk
from .base import ChunkingConfig
from .token_budget import TokenBudgeter, Block


def _split_paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if paras:
        return paras
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines


@dataclass
class TextChunker:
    name: str = "text"

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
        parts = _split_paragraphs(text)
        blocks: List[Block] = []

        for i, p in enumerate(parts):
            parent_id = f"{source_id}:text:para:{i}"
            parent_meta: Dict[str, Any] = {"kind": "paragraph", "level": config.parent_level_name, "parent_id": parent_id}

            if config.emit_parent_chunks:
                blocks.append(Block(p, dict(parent_meta)))

            if config.hierarchical:
                micro = self.budgeter.split_text_micro(
                    p,
                    target_tokens=config.micro_chunk_tokens,
                    overlap_tokens=config.micro_overlap_tokens,
                    hard_cap_tokens=config.micro_hard_cap_tokens or config.hard_cap_tokens,
                    strategy="paragraphs",
                )
            else:
                micro = [p]

            for j, mp in enumerate(micro):
                child_meta = dict(parent_meta)
                child_meta["kind"] = "paragraph_child"
                child_meta["level"] = config.child_level_name
                child_meta["parent_id"] = parent_id
                child_meta["child_index"] = j
                blocks.append(Block(mp, child_meta))

        if not blocks and text.strip():
            blocks = [Block(text.strip(), {"kind": "raw", "level": config.child_level_name})]

        base_meta: Dict[str, Any] = {"source_id": source_id, "ext": ext, "lang": None, "chunker": self.name}
        return self.budgeter.pack_blocks(
            blocks,
            source_id=source_id,
            base_meta=base_meta,
            chunk_tokens=config.chunk_tokens,
            overlap_tokens=config.overlap_tokens,
            hard_cap_tokens=config.hard_cap_tokens,
            chunk_id_prefix=self.name,
        )
