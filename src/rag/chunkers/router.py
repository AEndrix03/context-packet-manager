from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from src.rag.schema import Chunk  # adjust if needed
from .base import ChunkingConfig, BaseChunker
from .token_budget import TokenBudgeter
from .treesitter_generic import TreeSitterGenericChunker
from .java_ast import JavaAstChunker
from .python_ast import PythonAstChunker
from .markdown import MarkdownChunker
from .text import TextChunker
from .brace_fallback import BraceFallbackChunker


@dataclass
class ChunkerRouter:
    """
    Final developer router:
    - auto mode: pick best chunker per ext
    - multi mode: run multiple chunkers and merge (tagged by metadata.chunker)
    """

    def __init__(self, token_budgeter: Optional[TokenBudgeter] = None):
        self.budgeter = token_budgeter or TokenBudgeter()

        # instantiate chunkers
        self.chunkers: Dict[str, Any] = {
            "treesitter": TreeSitterGenericChunker(token_budgeter=self.budgeter),
            "java_ast": JavaAstChunker(token_budgeter=self.budgeter),
            "python_ast": PythonAstChunker(token_budgeter=self.budgeter),
            "markdown": MarkdownChunker(token_budgeter=self.budgeter),
            "text": TextChunker(token_budgeter=self.budgeter),
            "brace": BraceFallbackChunker(token_budgeter=self.budgeter),
        }

    def chunk(
        self,
        text: str,
        source_id: str,
        *,
        ext: str,
        config: Optional[ChunkingConfig] = None,
        **kwargs: Any,
    ) -> List[Chunk]:
        config = config or ChunkingConfig()

        if config.mode == "multi":
            names = config.multi_chunkers or ["treesitter", "brace", "text"]
            return self._multi(text, source_id, ext=ext, config=config, names=names, **kwargs)

        # auto
        name = self._pick_auto(ext)
        return self._run(name, text, source_id, ext=ext, config=config, **kwargs)

    def _pick_auto(self, ext: str) -> str:
        e = ext.lower()
        if e == ".java":
            return "java_ast"
        if e == ".py":
            return "python_ast"
        if e == ".md":
            return "markdown"
        if e in (".txt", ".rst"):
            return "text"
        # code-ish: prefer treesitter then brace fallback
        if e in (".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb", ".kt", ".swift", ".json", ".yaml", ".yml", ".xml"):
            return "treesitter"
        return "text"

    def _run(self, name: str, text: str, source_id: str, *, ext: str, config: ChunkingConfig, **kwargs: Any) -> List[Chunk]:
        ch = self.chunkers.get(name)
        if ch is None:
            ch = self.chunkers["text"]
            name = "text"
        return ch.chunk(text, source_id, ext=ext, config=config, **kwargs)

    def _multi(
        self,
        text: str,
        source_id: str,
        *,
        ext: str,
        config: ChunkingConfig,
        names: Sequence[str],
        **kwargs: Any,
    ) -> List[Chunk]:
        all_chunks: List[Chunk] = []
        seen: set[str] = set()

        for name in names:
            chunks = self._run(name, text, source_id, ext=ext, config=config, **kwargs)
            for c in chunks:
                # de-dup by text hash-ish
                key = (c.text[:2000], c.metadata.get("chunker"), c.metadata.get("lang"), c.metadata.get("ext"))
                sk = str(hash(key))
                if sk in seen:
                    continue
                seen.add(sk)
                # tag multi
                c.metadata["chunk_mode"] = "multi"
                all_chunks.append(c)

        return all_chunks
