"""
ChunkerRouter - Updated with the new JavaChunker.

Differences from original router.py:
- Uses new JavaChunker instead of JavaAstChunker
- Better fallback chain for Java files
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from ..schema import Chunk
from .base import ChunkingConfig, BaseChunker
from .token_budget import TokenBudgeter
from .treesitter_generic import TreeSitterGenericChunker
from .java import JavaChunker  # NEW: Import the new JavaChunker
from .python_ast import PythonAstChunker
from .markdown import MarkdownChunker
from .text import TextChunker
from .brace_fallback import BraceFallbackChunker


@dataclass
class ChunkerRouter:
    """
    Production router for code/text chunking:
    - auto mode: pick best chunker per extension
    - multi mode: run multiple chunkers and merge (tagged by metadata.chunker)
    """

    def __init__(self, token_budgeter: Optional[TokenBudgeter] = None):
        self.budgeter = token_budgeter or TokenBudgeter()

        # Instantiate all chunkers with shared token budgeter
        self.chunkers: Dict[str, Any] = {
            "treesitter": TreeSitterGenericChunker(token_budgeter=self.budgeter),
            "java": JavaChunker(token_budgeter=self.budgeter),  # NEW: Production Java chunker
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
        """
        Chunk text using the appropriate chunker based on mode and extension.

        Args:
            text: Source code or text to chunk
            source_id: Unique identifier for the source (usually file path)
            ext: File extension (e.g., ".java", ".py", ".md")
            config: Chunking configuration (uses defaults if None)
            **kwargs: Additional arguments passed to chunkers

        Returns:
            List of Chunk objects
        """
        config = config or ChunkingConfig()

        if config.mode == "multi":
            names = config.multi_chunkers or ["treesitter", "brace", "text"]
            return self._multi(text, source_id, ext=ext, config=config, names=names, **kwargs)

        # Auto mode: pick best chunker
        name = self._pick_auto(ext)
        return self._run(name, text, source_id, ext=ext, config=config, **kwargs)

    def _pick_auto(self, ext: str) -> str:
        """
        Select the best chunker for a given file extension.

        Priority:
        1. Language-specific chunkers (java, python_ast)
        2. Generic tree-sitter for supported languages
        3. Markdown for documentation
        4. Text fallback
        """
        e = ext.lower()

        # Java - use the production Java chunker
        if e == ".java":
            return "java"

        # Python - use AST-based chunker
        if e == ".py":
            return "python_ast"

        # Markdown
        if e == ".md":
            return "markdown"

        # Plain text
        if e in (".txt", ".rst"):
            return "text"

        # Other code files - use tree-sitter generic
        if e in (
                ".js", ".jsx", ".ts", ".tsx",
                ".html", ".css", ".scss",
                ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
                ".cs", ".php", ".rb", ".kt", ".swift",
                ".json", ".yaml", ".yml", ".xml",
        ):
            return "treesitter"

        # Default fallback
        return "text"

    def _run(
            self,
            name: str,
            text: str,
            source_id: str,
            *,
            ext: str,
            config: ChunkingConfig,
            **kwargs: Any,
    ) -> List[Chunk]:
        """Run a specific chunker by name."""
        chunker = self.chunkers.get(name)

        if chunker is None:
            # Fallback to text chunker
            chunker = self.chunkers["text"]
            name = "text"

        return chunker.chunk(text, source_id, ext=ext, config=config, **kwargs)

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
        """
        Run multiple chunkers and merge results (deduped).
        Useful for getting multiple "views" of the same code.
        """
        all_chunks: List[Chunk] = []
        seen: set[str] = set()

        for name in names:
            chunks = self._run(name, text, source_id, ext=ext, config=config, **kwargs)

            for c in chunks:
                # Deduplicate by text content + metadata
                key = (
                    c.text[:2000],  # First 2000 chars
                    c.metadata.get("chunker"),
                    c.metadata.get("lang"),
                    c.metadata.get("ext"),
                )
                sk = str(hash(key))

                if sk in seen:
                    continue

                seen.add(sk)
                c.metadata["chunk_mode"] = "multi"
                all_chunks.append(c)

        return all_chunks

    def get_available_chunkers(self) -> List[str]:
        """Return list of available chunker names."""
        return list(self.chunkers.keys())

    def get_chunker(self, name: str) -> Optional[Any]:
        """Get a specific chunker by name."""
        return self.chunkers.get(name)