from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.rag.schema import Chunk
from .base import ChunkingConfig
from .token_budget import TokenBudgeter
from .treesitter_generic import TreeSitterGenericChunker


@dataclass
class JavaAstChunker:
    name: str = "java_ast"

    def __init__(self, token_budgeter: Optional[TokenBudgeter] = None):
        self.budgeter = token_budgeter or TokenBudgeter()
        self.ts = TreeSitterGenericChunker(token_budgeter=self.budgeter)

    def chunk(
        self,
        text: str,
        source_id: str,
        *,
        ext: str,
        config: ChunkingConfig,
        **kwargs: Any,
    ) -> List[Chunk]:
        chunks = self.ts.chunk(text, source_id, ext=ext, config=config, language="java")
        if not chunks:
            return chunks

        header = self._extract_java_header(text, max_chars=config.max_header_chars)

        # tag chunker name as java_ast
        for ch in chunks:
            ch.metadata["chunker"] = self.name
            ch.metadata["lang"] = "java"

        # if TS header isn't good enough, inject our java header into CHILD chunks
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

    def _extract_java_header(self, text: str, max_chars: int) -> str:
        lines = text.splitlines()
        header_lines: List[str] = []

        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1

        # initial block comment/javadoc
        if i < len(lines) and lines[i].lstrip().startswith("/*"):
            header_lines.append(lines[i])
            i += 1
            while i < len(lines):
                header_lines.append(lines[i])
                if "*/" in lines[i]:
                    i += 1
                    break
                i += 1

        for line in lines[i:]:
            s = line.strip()
            if s.startswith("package ") or s.startswith("import "):
                header_lines.append(line)
                continue
            if any(s.startswith(k) for k in ("public ", "private ", "protected ", "class ", "interface ", "enum ", "record ", "@")):
                if s.startswith("@"):
                    header_lines.append(line)
                    continue
                if any(s.startswith(k) for k in ("class ", "interface ", "enum ", "record ")) or (" class " in s) or (" interface " in s) or (" enum " in s) or (" record " in s):
                    header_lines.append(line)
                break

        header = "\n".join([h for h in header_lines if h.strip()]).strip()
        return header[:max_chars] if header else ""
