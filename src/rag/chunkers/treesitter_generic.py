from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.rag.schema import Chunk
from .base import ChunkingConfig
from .token_budget import TokenBudgeter, Block

try:
    from tree_sitter_language_pack import get_parser  # type: ignore
except Exception:
    try:
        from tree_sitter_languages import get_parser  # type: ignore
    except Exception:
        get_parser = None  # type: ignore


LANG_BY_EXT: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".php": "php",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".swift": "swift",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
}

INTERESTING_NODES: Dict[str, set[str]] = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition"},
    "typescript": {"function_declaration", "class_declaration", "method_definition", "interface_declaration", "enum_declaration", "type_alias_declaration"},
    "tsx": {"function_declaration", "class_declaration", "method_definition", "interface_declaration", "enum_declaration", "type_alias_declaration"},
    "java": {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration", "method_declaration", "constructor_declaration"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "rust": {"function_item", "impl_item", "struct_item", "enum_item", "trait_item", "mod_item"},
    "html": {"element"},
    "css": {"rule_set", "at_rule"},
    "scss": {"rule_set", "at_rule"},
}

HEADER_NODES: Dict[str, set[str]] = {
    "java": {"package_declaration", "import_declaration"},
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
    "go": {"package_clause", "import_declaration"},
    "rust": {"use_declaration", "mod_item"},
    "html": set(),
    "css": set(),
    "scss": set(),
}


def _node_text(src_bytes: bytes, node) -> str:
    return src_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _safe_symbol_name(node, src_bytes: bytes) -> Optional[str]:
    try:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return _node_text(src_bytes, name_node).strip()
    except Exception:
        pass
    return None


@dataclass
class TreeSitterGenericChunker:
    name: str = "treesitter"

    def __init__(self, token_budgeter: Optional[TokenBudgeter] = None):
        self.budgeter = token_budgeter or TokenBudgeter()

    def chunk(
        self,
        text: str,
        source_id: str,
        *,
        ext: str,
        config: ChunkingConfig,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Chunk]:
        if get_parser is None:
            return self._fallback_lines(text, source_id, ext, config, reason="missing_tree_sitter")

        lang = language or LANG_BY_EXT.get(ext.lower())
        if not lang:
            return self._fallback_lines(text, source_id, ext, config, reason="unknown_language")

        try:
            parser = get_parser(lang)
        except Exception:
            return self._fallback_lines(text, source_id, ext, config, reason="parser_load_failed")

        src_bytes = text.encode("utf-8", errors="replace")
        tree = parser.parse(src_bytes)
        root = tree.root_node

        interesting = INTERESTING_NODES.get(lang, set())
        header_types = HEADER_NODES.get(lang, set())

        blocks: List[Block] = []

        # header/preamble block
        header_text = ""
        if config.include_source_preamble and header_types:
            header_parts: List[str] = []
            for ch in root.children:
                if ch.type in header_types:
                    header_parts.append(_node_text(src_bytes, ch).strip())
            if header_parts:
                header_text = "\n".join(header_parts).strip()[: config.max_header_chars]
                blocks.append(Block(header_text, {"kind": "preamble", "lang": lang, "level": config.parent_level_name}))

        def emit_symbol_block(sym_text: str, *, node_type: str, symbol: Optional[str], line_start: int, line_end: int):
            sym_text = sym_text.strip()
            if not sym_text:
                return

            parent_id = f"{source_id}:{lang}:{node_type}:{symbol or 'anon'}:{line_start}-{line_end}"

            parent_meta = {
                "kind": "symbol",
                "node_type": node_type,
                "symbol": symbol,
                "lang": lang,
                "line_start": line_start,
                "line_end": line_end,
                "level": config.parent_level_name,
                "parent_id": parent_id,  # self-id for parent
            }

            # optionally emit parent chunk
            if config.emit_parent_chunks:
                blocks.append(Block(sym_text, dict(parent_meta)))

            # emit children
            if config.hierarchical:
                micro_cap = config.micro_hard_cap_tokens or config.hard_cap_tokens
                parts = self.budgeter.split_text_micro(
                    sym_text,
                    target_tokens=config.micro_chunk_tokens,
                    overlap_tokens=config.micro_overlap_tokens,
                    hard_cap_tokens=micro_cap,
                    strategy=config.micro_split_strategy,
                )
                for j, p in enumerate(parts):
                    child_meta = dict(parent_meta)
                    child_meta["level"] = config.child_level_name
                    child_meta["parent_id"] = parent_id
                    child_meta["child_index"] = j
                    child_meta["kind"] = "symbol_child"
                    blocks.append(Block(p, child_meta))
            else:
                # fallback: treat symbol as one block
                child_meta = dict(parent_meta)
                child_meta["level"] = config.child_level_name
                child_meta["parent_id"] = parent_id
                child_meta["kind"] = "symbol_child"
                blocks.append(Block(sym_text, child_meta))

        # collect interesting nodes
        def collect(node, depth: int = 0):
            if depth > 4:
                return
            for ch in node.children:
                if ch.type in interesting:
                    sym = _safe_symbol_name(ch, src_bytes)
                    ls = ch.start_point[0] + 1
                    le = ch.end_point[0] + 1
                    emit_symbol_block(
                        _node_text(src_bytes, ch),
                        node_type=ch.type,
                        symbol=sym,
                        line_start=ls,
                        line_end=le,
                    )
                else:
                    collect(ch, depth + 1)

        collect(root)

        if not blocks:
            return self._fallback_lines(text, source_id, ext, config, reason="no_blocks")

        base_meta: Dict[str, Any] = {"source_id": source_id, "ext": ext, "lang": lang, "chunker": self.name}

        # pack blocks into final chunks (still useful when micro parts are tiny)
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

        # optional: context injection (prepend header to children only)
        if config.include_context_in_children and header_text:
            out: List[Chunk] = []
            for ch in chunks:
                bms = ch.metadata.get("blocks_meta") or []
                is_child = any(isinstance(bm, dict) and bm.get("level") == config.child_level_name for bm in bms)
                if is_child:
                    out.append(Chunk(id=ch.id, text=f"{header_text}\n\n{ch.text}", metadata=ch.metadata))
                else:
                    out.append(ch)
            return out

        return chunks

    def _fallback_lines(self, text: str, source_id: str, ext: str, config: ChunkingConfig, reason: str) -> List[Chunk]:
        lines = [l for l in text.splitlines() if l.strip()]
        blocks = [Block(line, {"kind": "line", "level": config.child_level_name}) for line in lines]
        if not blocks:
            blocks = [Block(text.strip(), {"kind": "raw", "level": config.child_level_name})] if text.strip() else []
        base_meta = {"source_id": source_id, "ext": ext, "lang": None, "chunker": f"{self.name}:fallback", "reason": reason}
        return self.budgeter.pack_blocks(
            blocks,
            source_id=source_id,
            base_meta=base_meta,
            chunk_tokens=config.chunk_tokens,
            overlap_tokens=config.overlap_tokens,
            hard_cap_tokens=config.hard_cap_tokens,
            chunk_id_prefix=f"{self.name}_fallback",
        )
