"""Deterministic file classification and language detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileClassification:
    pipeline: str
    language: str
    mime: str
    is_supported_text: bool = True


PIPELINES_BY_EXT: dict[str, FileClassification] = {
    # Core languages (existing)
    ".java": FileClassification("java", "java", "text/x-java"),
    ".py": FileClassification("code_generic", "python", "text/x-python"),
    ".js": FileClassification("code_generic", "javascript", "text/javascript"),
    ".ts": FileClassification("code_generic", "typescript", "text/typescript"),
    ".tsx": FileClassification("code_generic", "typescript", "text/typescript"),
    ".go": FileClassification("code_generic", "go", "text/x-go"),
    ".rs": FileClassification("code_generic", "rust", "text/x-rust"),
    ".c": FileClassification("code_generic", "c", "text/x-c"),
    ".cpp": FileClassification("code_generic", "cpp", "text/x-c++"),
    ".cc": FileClassification("code_generic", "cpp", "text/x-c++"),
    ".cxx": FileClassification("code_generic", "cpp", "text/x-c++"),
    ".h": FileClassification("code_generic", "c", "text/x-c"),
    ".hpp": FileClassification("code_generic", "cpp", "text/x-c++"),
    ".cs": FileClassification("code_generic", "csharp", "text/x-csharp"),
    # JVM languages
    ".kt": FileClassification("code_generic", "kotlin", "text/x-kotlin"),
    ".kts": FileClassification("code_generic", "kotlin", "text/x-kotlin"),
    ".scala": FileClassification("code_generic", "scala", "text/x-scala"),
    ".groovy": FileClassification("code_generic", "groovy", "text/x-groovy"),
    ".gradle": FileClassification("code_generic", "groovy", "text/x-groovy"),
    # Mobile
    ".dart": FileClassification("code_generic", "dart", "text/x-dart"),
    ".swift": FileClassification("code_generic", "swift", "text/x-swift"),
    ".m": FileClassification("code_generic", "objc", "text/x-objc"),
    ".mm": FileClassification("code_generic", "objcpp", "text/x-objc++"),
    # Web / Frontend
    ".jsx": FileClassification("code_generic", "javascript", "text/javascript"),
    ".vue": FileClassification("code_generic", "vue", "text/x-vue"),
    ".scss": FileClassification("code_generic", "scss", "text/x-scss"),
    ".sass": FileClassification("code_generic", "sass", "text/x-sass"),
    ".less": FileClassification("code_generic", "less", "text/x-less"),
    ".css": FileClassification("code_generic", "css", "text/css"),
    # Scripting
    ".php": FileClassification("code_generic", "php", "text/x-php"),
    ".rb": FileClassification("code_generic", "ruby", "text/x-ruby"),
    ".lua": FileClassification("code_generic", "lua", "text/x-lua"),
    ".sh": FileClassification("code_generic", "shell", "text/x-shellscript"),
    ".bash": FileClassification("code_generic", "shell", "text/x-shellscript"),
    ".zsh": FileClassification("code_generic", "shell", "text/x-shellscript"),
    ".ps1": FileClassification("code_generic", "powershell", "text/x-powershell"),
    ".pl": FileClassification("code_generic", "perl", "text/x-perl"),
    # Systems / Other
    ".zig": FileClassification("code_generic", "zig", "text/x-zig"),
    ".ex": FileClassification("code_generic", "elixir", "text/x-elixir"),
    ".exs": FileClassification("code_generic", "elixir", "text/x-elixir"),
    ".erl": FileClassification("code_generic", "erlang", "text/x-erlang"),
    ".hrl": FileClassification("code_generic", "erlang", "text/x-erlang"),
    ".clj": FileClassification("code_generic", "clojure", "text/x-clojure"),
    ".cljs": FileClassification("code_generic", "clojure", "text/x-clojure"),
    ".hs": FileClassification("code_generic", "haskell", "text/x-haskell"),
    ".ml": FileClassification("code_generic", "ocaml", "text/x-ocaml"),
    ".r": FileClassification("code_generic", "r", "text/x-r"),
    # Config / Data
    ".toml": FileClassification("text", "toml", "application/toml"),
    ".xml": FileClassification("text", "xml", "text/xml"),
    ".proto": FileClassification("code_generic", "protobuf", "text/x-protobuf"),
    ".sql": FileClassification("code_generic", "sql", "text/x-sql"),
    ".tf": FileClassification("code_generic", "terraform", "text/x-terraform"),
    ".hcl": FileClassification("code_generic", "hcl", "text/x-hcl"),
    ".dockerfile": FileClassification("code_generic", "dockerfile", "text/x-dockerfile"),
    ".json": FileClassification("json", "json", "application/json"),
    ".yml": FileClassification("yaml", "yaml", "application/yaml"),
    ".yaml": FileClassification("yaml", "yaml", "application/yaml"),
    # Documentation
    ".md": FileClassification("markdown", "markdown", "text/markdown"),
    ".markdown": FileClassification("markdown", "markdown", "text/markdown"),
    ".html": FileClassification("html", "html", "text/html"),
    ".htm": FileClassification("html", "html", "text/html"),
    ".txt": FileClassification("text", "text", "text/plain"),
    ".rst": FileClassification("text", "rst", "text/plain"),
    ".adoc": FileClassification("text", "asciidoc", "text/plain"),
    ".tex": FileClassification("text", "latex", "text/x-tex"),
}


LANGUAGE_HINTS: dict[str, str] = {
    "kotlin": "Use 'fun' keyword for functions, 'class'/'object'/'data class' for types.",
    "dart": "Use 'class' and methods. Widgets extend StatelessWidget/StatefulWidget.",
    "swift": "Use 'func', 'class', 'struct', 'protocol', 'extension'.",
    "vue": "File has <template>, <script>, <style> sections. Split by section first.",
    "php": "Functions start with 'function', classes with 'class'.",
    "typescript": "Angular: look for @Component, @Injectable decorators as chunk boundaries.",
    "sql": "Chunk by statement: CREATE, ALTER, INSERT, SELECT blocks.",
    "protobuf": "Chunk by message, enum, service definitions.",
    "terraform": "Chunk by resource, module, variable, output blocks.",
    "shell": "Chunk by function definition or logical comment blocks.",
    "scala": "Look for 'object', 'class', 'trait', 'def' keywords.",
    "ruby": "Functions use 'def', classes use 'class', modules use 'module'.",
    "elixir": "Look for 'defmodule', 'def', 'defp' for functions.",
    "haskell": "Functions defined with pattern matching, use type signatures.",
    "clojure": "S-expressions with (defn ...), (defmacro ...), (def ...).",
}


def language_hints(classification: FileClassification) -> str:
    """Return language-specific hints for the LLM chunker."""
    return LANGUAGE_HINTS.get(classification.language, "")


def classify_file(path: Path, content: str) -> FileClassification:
    ext = path.suffix.lower()
    known = PIPELINES_BY_EXT.get(ext)
    if known is not None:
        return known

    # Check for Dockerfile without extension
    if path.name.lower() in {"dockerfile", "containerfile"}:
        return FileClassification("code_generic", "dockerfile", "text/x-dockerfile")

    head = content.lstrip()[:128]
    if head.startswith("#!"):
        if "python" in head:
            return FileClassification("code_generic", "python", "text/x-python")
        if "bash" in head or "sh" in head:
            return FileClassification("code_generic", "shell", "text/x-shellscript")
        if "node" in head:
            return FileClassification("code_generic", "javascript", "text/javascript")
        if "ruby" in head:
            return FileClassification("code_generic", "ruby", "text/x-ruby")
        if "perl" in head:
            return FileClassification("code_generic", "perl", "text/x-perl")

    if "\x00" in content:
        return FileClassification(
            pipeline="binary_unsupported",
            language="binary",
            mime="application/octet-stream",
            is_supported_text=False,
        )

    return FileClassification("text", "text", "text/plain")

