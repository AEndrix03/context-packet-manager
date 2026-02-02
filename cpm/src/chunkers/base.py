from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from schema import Chunk


@dataclass(frozen=True)
class ChunkingConfig:
    # token budget (pack finale, come prima)
    chunk_tokens: int = 800
    overlap_tokens: int = 120
    hard_cap_tokens: Optional[int] = None  # es. embedder.max_seq_length - 32

    # behavior
    include_source_preamble: bool = True
    include_context_in_children: bool = True  # prepend header to children (context injection)
    max_header_chars: int = 6000  # safety cap

    # chunk packing (especially important for code)
    max_symbol_blocks_per_chunk: int = 1
    separate_preamble_chunk: bool = True

    # router / misc
    mode: str = "auto"  # "auto" | "multi"
    multi_chunkers: Optional[List[str]] = None  # used when mode="multi"

    # -------- NEW: hierarchical chunking ----------
    hierarchical: bool = True

    # micro-chunking inside each parent (symbol/section)
    micro_chunk_tokens: int = 220
    micro_overlap_tokens: int = 40
    micro_hard_cap_tokens: Optional[int] = None  # if None uses hard_cap_tokens

    # output control
    emit_parent_chunks: bool = False  # default: ONLY children (better for FAISS)
    parent_level_name: str = "parent"
    child_level_name: str = "child"

    # how to split micro chunks
    micro_split_strategy: str = "lines"  # "lines" (robust) | "paragraphs" (text-ish)

    # allow passing extra options
    extra: Optional[Dict[str, Any]] = None


class BaseChunker(Protocol):
    name: str

    def chunk(
        self,
        text: str,
        source_id: str,
        *,
        ext: str,
        config: ChunkingConfig,
        **kwargs: Any,
    ) -> List[Chunk]:
        ...
