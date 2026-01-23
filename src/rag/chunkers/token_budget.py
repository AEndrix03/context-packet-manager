from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Dict, Any, Iterable

from src.rag.schema import Chunk


TokenCounter = Callable[[str], int]


def _default_token_counter(text: str) -> int:
    """
    Fallback cheap token estimator (no deps). Not perfect, but stable.
    """
    if not text:
        return 0
    return max(1, len(text.split()))


@dataclass
class Block:
    text: str
    meta: Dict[str, Any]


class TokenBudgeter:
    """
    Packs blocks (logical units) into chunks by token budget with overlap.
    Also provides a micro-split helper to create hierarchical (parent->children) chunks.
    """

    def __init__(self, token_counter: Optional[TokenCounter] = None):
        self.token_counter = token_counter or _default_token_counter

    # ---------- NEW ----------
    def split_text_micro(
        self,
        text: str,
        *,
        target_tokens: int,
        overlap_tokens: int,
        hard_cap_tokens: Optional[int] = None,
        strategy: str = "lines",
    ) -> List[str]:
        """
        Split a parent text into micro parts WITHOUT any parsing dependencies.

        strategy:
          - "lines": robust for code and logs (packs by lines)
          - "paragraphs": better for prose (packs by paragraphs then lines fallback)
        """
        if not text.strip():
            return []

        cap = hard_cap_tokens
        target = max(1, target_tokens if cap is None else min(target_tokens, cap))
        overlap = min(max(0, overlap_tokens), max(0, target - 1))

        if strategy == "paragraphs":
            units = [p for p in (x.strip() for x in text.split("\n\n")) if p]
            if not units:
                units = [l for l in (x.rstrip() for x in text.splitlines()) if l.strip()]
        else:
            units = [l for l in (x.rstrip() for x in text.splitlines()) if l.strip()]
            if not units:
                units = [text.strip()]

        parts: List[str] = []
        buf: List[str] = []
        buf_tokens = 0

        def flush() -> None:
            nonlocal buf, buf_tokens
            if not buf:
                return
            s = "\n".join(buf).strip()
            if s:
                parts.append(s)

            if overlap == 0:
                buf, buf_tokens = [], 0
                return

            # keep tail units until overlap satisfied
            new_buf: List[str] = []
            new_tokens = 0
            for u in reversed(buf):
                ut = self.token_counter(u)
                if new_buf and (new_tokens + ut > overlap):
                    break
                new_buf.append(u)
                new_tokens += ut
            new_buf.reverse()
            buf, buf_tokens = new_buf, new_tokens

        for u in units:
            ut = self.token_counter(u)

            # hard split a single huge unit by lines if needed
            if cap is not None and ut > cap:
                flush()
                # split that unit by raw lines
                sub_lines = [x.rstrip() for x in u.splitlines() if x.strip()]
                if not sub_lines:
                    sub_lines = [u]
                sub_buf: List[str] = []
                sub_tokens = 0
                for sl in sub_lines:
                    st = self.token_counter(sl)
                    if sub_buf and (sub_tokens + st > cap):
                        ss = "\n".join(sub_buf).strip()
                        if ss:
                            parts.append(ss)
                        sub_buf, sub_tokens = [], 0
                    sub_buf.append(sl)
                    sub_tokens += st
                if sub_buf:
                    ss = "\n".join(sub_buf).strip()
                    if ss:
                        parts.append(ss)
                continue

            if buf and (buf_tokens + ut > target):
                flush()

            buf.append(u)
            buf_tokens += ut

        flush()
        return parts

    def pack_blocks(
        self,
        blocks: Sequence[Block],
        *,
        source_id: str,
        base_meta: Dict[str, Any],
        chunk_tokens: int,
        overlap_tokens: int,
        hard_cap_tokens: Optional[int] = None,
        max_symbol_blocks_per_chunk: int = 999,
        chunk_id_prefix: str = "chunk",
    ) -> List[Chunk]:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be > 0")
        if overlap_tokens < 0:
            raise ValueError("overlap_tokens must be >= 0")
        if max_symbol_blocks_per_chunk <= 0:
            raise ValueError("max_symbol_blocks_per_chunk must be > 0")

        cap = hard_cap_tokens
        target = chunk_tokens if cap is None else min(chunk_tokens, cap)
        overlap = min(overlap_tokens, max(0, target - 1))

        chunks: List[Chunk] = []
        buf_texts: List[str] = []
        buf_meta: List[Dict[str, Any]] = []
        buf_tokens = 0
        buf_symbol_blocks = 0  # count blocks where meta.kind == 'symbol'

        def flush() -> None:
            nonlocal buf_texts, buf_meta, buf_tokens, buf_symbol_blocks

            if not buf_texts:
                return

            joined = "\n".join(buf_texts).strip()
            if not joined:
                buf_texts, buf_meta, buf_tokens, buf_symbol_blocks = [], [], 0, 0
                return

            cid = f"{source_id}:{chunk_id_prefix}:{len(chunks)}"
            meta = dict(base_meta)
            meta["block_count"] = len(buf_texts)
            meta["blocks_meta"] = buf_meta
            chunks.append(Chunk(id=cid, text=joined, metadata=meta))

            if overlap == 0:
                buf_texts, buf_meta, buf_tokens, buf_symbol_blocks = [], [], 0, 0
                return

            # Keep last blocks until overlap satisfied
            new_texts: List[str] = []
            new_meta: List[Dict[str, Any]] = []
            new_tokens = 0

            for t, m in reversed(list(zip(buf_texts, buf_meta))):
                ttok = self.token_counter(t)
                if new_tokens + ttok > overlap and new_texts:
                    break
                new_texts.append(t)
                new_meta.append(m)
                new_tokens += ttok

            new_texts.reverse()
            new_meta.reverse()
            buf_texts, buf_meta, buf_tokens = new_texts, new_meta, new_tokens
            buf_symbol_blocks = sum(1 for m in buf_meta if isinstance(m, dict) and m.get("kind") == "symbol")

        for block in blocks:
            is_symbol = bool(isinstance(block.meta, dict) and block.meta.get("kind") == "symbol")
            if is_symbol and buf_texts and buf_symbol_blocks >= max_symbol_blocks_per_chunk:
                flush()

            btok = self.token_counter(block.text)

            # If single block is too big, hard-split it by lines
            if cap is not None and btok > cap:
                flush()

                lines = block.text.splitlines()
                part: List[str] = []
                part_tokens = 0

                for line in lines:
                    lt = self.token_counter(line)
                    if part and part_tokens + lt > cap:
                        ptxt = "\n".join(part).strip()
                        if ptxt:
                            cid = f"{source_id}:{chunk_id_prefix}:{len(chunks)}"
                            meta = dict(base_meta)
                            meta["block_count"] = 1
                            meta["blocks_meta"] = [dict(block.meta, hard_split=True)]
                            chunks.append(Chunk(id=cid, text=ptxt, metadata=meta))
                        part, part_tokens = [], 0

                    part.append(line)
                    part_tokens += lt

                if part:
                    ptxt = "\n".join(part).strip()
                    if ptxt:
                        cid = f"{source_id}:{chunk_id_prefix}:{len(chunks)}"
                        meta = dict(base_meta)
                        meta["block_count"] = 1
                        meta["blocks_meta"] = [dict(block.meta, hard_split=True)]
                        chunks.append(Chunk(id=cid, text=ptxt, metadata=meta))

                buf_texts, buf_meta, buf_tokens, buf_symbol_blocks = [], [], 0, 0
                continue

            if buf_texts and (buf_tokens + btok > target):
                flush()

            buf_texts.append(block.text)
            buf_meta.append(block.meta)
            buf_tokens += btok
            if is_symbol:
                buf_symbol_blocks += 1

        flush()
        return chunks
