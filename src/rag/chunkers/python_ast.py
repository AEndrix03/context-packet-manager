from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import ast

from src.rag.schema import Chunk
from .base import ChunkingConfig
from .token_budget import TokenBudgeter, Block


def _get_text_slice_by_lines(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines()
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    return "\n".join(lines[start_idx:end_idx]).strip()


@dataclass
class PythonAstChunker:
    name: str = "python_ast"

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
        try:
            tree = ast.parse(text)
        except Exception:
            return self._fallback(text, source_id, ext, config, reason="ast_parse_failed")

        blocks: List[Block] = []
        header = self._extract_header(tree, text, max_chars=config.max_header_chars) if config.include_source_preamble else ""

        # preamble block (optional)
        if header:
            blocks.append(Block(header, {"kind": "preamble", "lang": "python", "level": config.parent_level_name}))

        def emit_symbol(snippet: str, *, node_type: str, symbol: str, line_start: int, line_end: int):
            snippet = snippet.strip()
            if not snippet:
                return

            parent_id = f"{source_id}:python:{node_type}:{symbol}:{line_start}-{line_end}"
            parent_meta = {
                "kind": "symbol",
                "node_type": node_type,
                "symbol": symbol,
                "lang": "python",
                "line_start": line_start,
                "line_end": line_end,
                "level": config.parent_level_name,
                "parent_id": parent_id,
            }

            if config.emit_parent_chunks:
                blocks.append(Block(snippet, dict(parent_meta)))

            micro_cap = config.micro_hard_cap_tokens or config.hard_cap_tokens
            if config.hierarchical:
                parts = self.budgeter.split_text_micro(
                    snippet,
                    target_tokens=config.micro_chunk_tokens,
                    overlap_tokens=config.micro_overlap_tokens,
                    hard_cap_tokens=micro_cap,
                    strategy=config.micro_split_strategy,
                )
            else:
                parts = [snippet]

            for j, p in enumerate(parts):
                child_meta = dict(parent_meta)
                child_meta["kind"] = "symbol_child"
                child_meta["level"] = config.child_level_name
                child_meta["parent_id"] = parent_id
                child_meta["child_index"] = j
                blocks.append(Block(p, child_meta))

        # walk top-level defs/classes
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if start is None or end is None:
                    continue
                snippet = _get_text_slice_by_lines(text, start, end)
                symbol = getattr(node, "name", "anon")
                ntype = "class" if isinstance(node, ast.ClassDef) else "function"
                emit_symbol(snippet, node_type=ntype, symbol=symbol, line_start=start, line_end=end)

        if not blocks:
            return self._fallback(text, source_id, ext, config, reason="no_blocks")

        base_meta: Dict[str, Any] = {"source_id": source_id, "ext": ext, "lang": "python", "chunker": self.name}

        chunks: List[Chunk] = []
        blocks_to_pack = blocks

        if config.separate_preamble_chunk and blocks and isinstance(blocks[0].meta, dict) and blocks[0].meta.get("kind") == "preamble":
            chunks.extend(
                self.budgeter.pack_blocks(
                    [blocks[0]],
                    source_id=source_id,
                    base_meta=dict(base_meta, preamble=True),
                    chunk_tokens=config.chunk_tokens,
                    overlap_tokens=0,
                    hard_cap_tokens=config.hard_cap_tokens,
                    max_symbol_blocks_per_chunk=max(1, config.max_symbol_blocks_per_chunk),
                    chunk_id_prefix=self.name,
                )
            )
            blocks_to_pack = blocks[1:]

        if blocks_to_pack:
            chunks.extend(
                self.budgeter.pack_blocks(
                    blocks_to_pack,
                    source_id=source_id,
                    base_meta=base_meta,
                    chunk_tokens=config.chunk_tokens,
                    overlap_tokens=config.overlap_tokens,
                    hard_cap_tokens=config.hard_cap_tokens,
                    max_symbol_blocks_per_chunk=max(1, config.max_symbol_blocks_per_chunk),
                    chunk_id_prefix=self.name,
                )
            )

        # context injection: prepend header to CHILD chunks only
        if config.include_context_in_children and header:
            out: List[Chunk] = []
            for ch in chunks:
                bms = ch.metadata.get("blocks_meta") or []
                is_child = any(isinstance(bm, dict) and bm.get("level") == config.child_level_name for bm in bms)
                if is_child:
                    out.append(Chunk(id=ch.id, text=f"{header}\n\n{ch.text}", metadata=ch.metadata))
                else:
                    out.append(ch)
            return out

        return chunks

    def _extract_header(self, tree: ast.AST, text: str, max_chars: int) -> str:
        header_lines: List[str] = []
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(getattr(tree.body[0], "value", None), ast.Constant) and isinstance(tree.body[0].value.value, str):
            ds_node = tree.body[0]
            start = getattr(ds_node, "lineno", 1)
            end = getattr(ds_node, "end_lineno", start)
            header_lines.append(_get_text_slice_by_lines(text, start, end))

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None) or start
                if start:
                    header_lines.append(_get_text_slice_by_lines(text, start, end))
            elif isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                break

        header = "\n".join([h for h in header_lines if h.strip()]).strip()
        return header[:max_chars] if header else ""

    def _fallback(self, text: str, source_id: str, ext: str, config: ChunkingConfig, reason: str) -> List[Chunk]:
        # still hierarchical: paragraph -> micro
        blocks: List[Block] = []
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paras and text.strip():
            paras = [text.strip()]

        for i, p in enumerate(paras):
            parent_id = f"{source_id}:python:fallback:{i}"
            if config.emit_parent_chunks:
                blocks.append(Block(p, {"kind": "fallback_parent", "level": config.parent_level_name, "parent_id": parent_id}))

            parts = self.budgeter.split_text_micro(
                p,
                target_tokens=config.micro_chunk_tokens,
                overlap_tokens=config.micro_overlap_tokens,
                hard_cap_tokens=config.micro_hard_cap_tokens or config.hard_cap_tokens,
                strategy="paragraphs",
            ) if config.hierarchical else [p]

            for j, mp in enumerate(parts):
                blocks.append(Block(mp, {"kind": "fallback_child", "level": config.child_level_name, "parent_id": parent_id, "child_index": j}))

        base_meta = {"source_id": source_id, "ext": ext, "lang": "python", "chunker": f"{self.name}:fallback", "reason": reason}
        return self.budgeter.pack_blocks(
            blocks,
            source_id=source_id,
            base_meta=base_meta,
            chunk_tokens=config.chunk_tokens,
            overlap_tokens=config.overlap_tokens,
            hard_cap_tokens=config.hard_cap_tokens,
            chunk_id_prefix=f"{self.name}_fallback",
        )
