"""
Java Chunker - Production-grade chunker for Java source code.

Features:
- Full hierarchical parsing (package → class → nested class → method)
- Javadoc/comment association with symbols
- Annotation-aware with framework detection (Spring, JPA, Jakarta, etc.)
- Smart context injection (header + class context in every chunk)
- Micro-chunking for large methods/classes
- Rich metadata for filtered retrieval
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .schema import Chunk
from .base import ChunkingConfig
from .token_budget import TokenBudgeter, Block

try:
    from tree_sitter_language_pack import get_parser  # type: ignore
except Exception:
    try:
        from tree_sitter_languages import get_parser  # type: ignore
    except Exception:
        get_parser = None  # type: ignore

# ============================================================================
# FRAMEWORK / ANNOTATION DETECTION
# ============================================================================

FRAMEWORK_ANNOTATIONS: Dict[str, Dict[str, Set[str]]] = {
    "spring_core": {
        "stereotype": {"@Component", "@Service", "@Repository", "@Controller", "@RestController", "@Configuration"},
        "injection": {"@Autowired", "@Inject", "@Value", "@Qualifier", "@Primary", "@Lazy"},
        "lifecycle": {"@PostConstruct", "@PreDestroy", "@Bean", "@Scope"},
        "aop": {"@Aspect", "@Before", "@After", "@Around", "@Pointcut"},
    },
    "spring_web": {
        "mapping": {"@RequestMapping", "@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping", "@PatchMapping"},
        "params": {"@RequestBody", "@ResponseBody", "@PathVariable", "@RequestParam", "@RequestHeader", "@CookieValue"},
        "response": {"@ResponseStatus", "@ExceptionHandler", "@ControllerAdvice", "@RestControllerAdvice"},
        "validation": {"@Valid", "@Validated"},
    },
    "spring_data": {
        "repository": {"@Repository", "@Query", "@Modifying", "@Param"},
        "transaction": {"@Transactional", "@EnableTransactionManagement"},
    },
    "jpa_jakarta": {
        "entity": {"@Entity", "@Table", "@MappedSuperclass", "@Embeddable", "@Embedded"},
        "id": {"@Id", "@GeneratedValue", "@SequenceGenerator", "@TableGenerator", "@EmbeddedId", "@IdClass"},
        "mapping": {"@Column", "@JoinColumn", "@JoinTable", "@OrderBy", "@OrderColumn"},
        "relations": {"@OneToOne", "@OneToMany", "@ManyToOne", "@ManyToMany", "@ElementCollection"},
        "fetch": {"@Fetch", "@BatchSize", "@LazyCollection"},
        "lifecycle": {"@PrePersist", "@PostPersist", "@PreUpdate", "@PostUpdate", "@PreRemove", "@PostRemove"},
    },
    "lombok": {
        "data": {"@Data", "@Value", "@Builder", "@SuperBuilder", "@NoArgsConstructor", "@AllArgsConstructor",
                 "@RequiredArgsConstructor"},
        "accessors": {"@Getter", "@Setter", "@ToString", "@EqualsAndHashCode"},
        "utility": {"@Slf4j", "@Log", "@Log4j", "@Log4j2", "@CommonsLog", "@Cleanup", "@SneakyThrows"},
    },
    "validation": {
        "constraints": {"@NotNull", "@NotBlank", "@NotEmpty", "@Size", "@Min", "@Max", "@Pattern", "@Email", "@Past",
                        "@Future", "@Positive", "@Negative"},
    },
    "jackson": {
        "serialization": {"@JsonProperty", "@JsonIgnore", "@JsonInclude", "@JsonFormat", "@JsonSerialize",
                          "@JsonDeserialize"},
        "type": {"@JsonTypeInfo", "@JsonSubTypes", "@JsonTypeName"},
    },
    "testing": {
        "junit": {"@Test", "@BeforeEach", "@AfterEach", "@BeforeAll", "@AfterAll", "@Disabled", "@DisplayName",
                  "@Nested", "@ParameterizedTest"},
        "mockito": {"@Mock", "@InjectMocks", "@Spy", "@Captor", "@MockBean", "@SpyBean"},
        "spring_test": {"@SpringBootTest", "@WebMvcTest", "@DataJpaTest", "@MockMvc", "@AutoConfigureMockMvc"},
    },
}


def _detect_frameworks(annotations: List[str]) -> Dict[str, List[str]]:
    """Detect frameworks and categories from a list of annotations."""
    detected: Dict[str, List[str]] = {}
    annotation_set = {a.split("(")[0] for a in annotations}  # Strip params: @Entity(name="x") → @Entity

    for framework, categories in FRAMEWORK_ANNOTATIONS.items():
        for category, annots in categories.items():
            matches = annotation_set & annots
            if matches:
                key = f"{framework}.{category}"
                detected[key] = list(matches)

    return detected


def _classify_java_symbol(node_type: str, annotations: List[str]) -> str:
    """Classify a Java symbol for retrieval purposes."""
    annotation_set = {a.split("(")[0] for a in annotations}

    # Spring stereotypes
    if annotation_set & {"@Controller", "@RestController"}:
        return "controller"
    if annotation_set & {"@Service"}:
        return "service"
    if annotation_set & {"@Repository"}:
        return "repository"
    if annotation_set & {"@Configuration"}:
        return "configuration"
    if annotation_set & {"@Entity", "@MappedSuperclass"}:
        return "entity"
    if annotation_set & {"@Component"}:
        return "component"

    # Test classes
    if annotation_set & {"@SpringBootTest", "@WebMvcTest", "@DataJpaTest", "@Test"}:
        return "test"

    # Fallback to node type
    type_map = {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
        "annotation_type_declaration": "annotation",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    }
    return type_map.get(node_type, "unknown")


# ============================================================================
# TREE-SITTER HELPERS
# ============================================================================

def _node_text(src_bytes: bytes, node) -> str:
    """Extract text from a tree-sitter node."""
    return src_bytes[node.start_byte: node.end_byte].decode("utf-8", errors="replace")


def _get_node_name(node, src_bytes: bytes) -> Optional[str]:
    """Get the name of a declaration node."""
    name_node = node.child_by_field_name("name")
    if name_node:
        return _node_text(src_bytes, name_node).strip()
    return None


def _get_preceding_comments(node, src_bytes: bytes, lines: List[str]) -> str:
    """
    Extract Javadoc and comments immediately preceding a node.
    Handles both /** Javadoc */ and // line comments.
    """
    start_line = node.start_point[0]  # 0-indexed
    if start_line == 0:
        return ""

    comment_lines: List[str] = []
    i = start_line - 1

    while i >= 0:
        line = lines[i].strip()

        # Javadoc/block comment end
        if line.endswith("*/"):
            # Find the start of this comment block
            j = i
            while j >= 0:
                comment_lines.insert(0, lines[j])
                if lines[j].strip().startswith("/*"):
                    break
                j -= 1
            break
        # Line comment
        elif line.startswith("//"):
            comment_lines.insert(0, lines[i])
            i -= 1
        # Annotation (include it)
        elif line.startswith("@"):
            comment_lines.insert(0, lines[i])
            i -= 1
        # Empty line - stop if we already have comments
        elif not line:
            if comment_lines:
                break
            i -= 1
        # Other content - stop
        else:
            break

    return "\n".join(comment_lines).strip()


def _extract_annotations(node, src_bytes: bytes) -> List[str]:
    """Extract all annotations from a node (modifiers)."""
    annotations: List[str] = []

    # Check for modifiers field
    modifiers = node.child_by_field_name("modifiers")
    if modifiers:
        for child in modifiers.children:
            if child.type in ("annotation", "marker_annotation"):
                annotations.append(_node_text(src_bytes, child).strip())

    # Also check direct annotation children (some grammars)
    for child in node.children:
        if child.type in ("annotation", "marker_annotation"):
            annotations.append(_node_text(src_bytes, child).strip())

    return annotations


def _get_method_signature(node, src_bytes: bytes) -> str:
    """Extract a clean method signature (without body)."""
    # Find the body and exclude it
    body = node.child_by_field_name("body")
    if body:
        sig_end = body.start_byte
        sig = src_bytes[node.start_byte:sig_end].decode("utf-8", errors="replace").strip()
        # Clean up
        sig = re.sub(r'\s+', ' ', sig)
        return sig
    return _node_text(src_bytes, node).split("{")[0].strip()


def _get_field_declaration(node, src_bytes: bytes) -> Tuple[str, List[str]]:
    """Extract field type and names."""
    field_text = _node_text(src_bytes, node).strip()
    names: List[str] = []

    for child in node.children:
        if child.type == "variable_declarator":
            name_node = child.child_by_field_name("name")
            if name_node:
                names.append(_node_text(src_bytes, name_node).strip())

    return field_text, names


# ============================================================================
# JAVA SYMBOL STRUCTURES
# ============================================================================

@dataclass
class JavaSymbol:
    """Represents a parsed Java symbol with full context."""
    node_type: str  # class_declaration, method_declaration, etc.
    name: str
    full_text: str  # Complete text including body
    signature: str  # For methods: signature without body
    annotations: List[str]
    javadoc: str
    line_start: int
    line_end: int
    parent_class: Optional[str] = None
    parent_hierarchy: List[str] = field(default_factory=list)  # [OuterClass, InnerClass, ...]
    children: List["JavaSymbol"] = field(default_factory=list)

    # Computed
    frameworks: Dict[str, List[str]] = field(default_factory=dict)
    symbol_class: str = "unknown"

    def __post_init__(self):
        self.frameworks = _detect_frameworks(self.annotations)
        self.symbol_class = _classify_java_symbol(self.node_type, self.annotations)

    @property
    def qualified_name(self) -> str:
        """Full qualified name including parent hierarchy."""
        parts = self.parent_hierarchy + [self.name]
        return ".".join(parts)

    @property
    def context_header(self) -> str:
        """Generate a context header for this symbol."""
        parts = []
        if self.javadoc:
            parts.append(self.javadoc)
        for ann in self.annotations:
            parts.append(ann)
        if self.node_type == "method_declaration":
            parts.append(self.signature)
        else:
            # For classes, show first line (declaration)
            first_line = self.full_text.split("\n")[0].strip()
            parts.append(first_line)
        return "\n".join(parts)


@dataclass
class JavaFile:
    """Represents a parsed Java file."""
    package: str
    imports: List[str]
    top_level_symbols: List[JavaSymbol]
    raw_header: str  # package + imports as text

    @property
    def header_with_class(self) -> str:
        """Header including package and imports."""
        return self.raw_header


# ============================================================================
# JAVA PARSER
# ============================================================================

class JavaParser:
    """Parse Java source code into structured symbols."""

    DECLARATION_TYPES = {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
    }

    MEMBER_TYPES = {
        "method_declaration",
        "constructor_declaration",
        "field_declaration",
    }

    def __init__(self):
        if get_parser is None:
            raise RuntimeError("tree-sitter not available")
        self.parser = get_parser("java")

    def parse(self, text: str) -> JavaFile:
        """Parse Java source into structured representation."""
        src_bytes = text.encode("utf-8", errors="replace")
        tree = self.parser.parse(src_bytes)
        root = tree.root_node
        lines = text.splitlines()

        # Extract package and imports
        package = ""
        imports: List[str] = []
        header_end_line = 0

        for child in root.children:
            if child.type == "package_declaration":
                package = _node_text(src_bytes, child).strip()
                header_end_line = max(header_end_line, child.end_point[0] + 1)
            elif child.type == "import_declaration":
                imports.append(_node_text(src_bytes, child).strip())
                header_end_line = max(header_end_line, child.end_point[0] + 1)

        raw_header = "\n".join(lines[:header_end_line]).strip()

        # Parse top-level declarations
        top_level: List[JavaSymbol] = []

        for child in root.children:
            if child.type in self.DECLARATION_TYPES:
                symbol = self._parse_declaration(child, src_bytes, lines, parent_hierarchy=[])
                if symbol:
                    top_level.append(symbol)

        return JavaFile(
            package=package,
            imports=imports,
            top_level_symbols=top_level,
            raw_header=raw_header,
        )

    def _parse_declaration(
            self,
            node,
            src_bytes: bytes,
            lines: List[str],
            parent_hierarchy: List[str],
    ) -> Optional[JavaSymbol]:
        """Parse a class/interface/enum/record declaration."""
        name = _get_node_name(node, src_bytes)
        if not name:
            return None

        annotations = _extract_annotations(node, src_bytes)
        javadoc = _get_preceding_comments(node, src_bytes, lines)
        full_text = _node_text(src_bytes, node)

        # For type declarations, signature is the first line
        first_line = full_text.split("{")[0].strip() + " {"

        symbol = JavaSymbol(
            node_type=node.type,
            name=name,
            full_text=full_text,
            signature=first_line,
            annotations=annotations,
            javadoc=javadoc,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_hierarchy=parent_hierarchy,
        )

        # Parse children (methods, nested classes, etc.)
        new_hierarchy = parent_hierarchy + [name]
        body = node.child_by_field_name("body")

        if body:
            for child in body.children:
                if child.type in self.DECLARATION_TYPES:
                    # Nested class/interface/enum
                    nested = self._parse_declaration(child, src_bytes, lines, new_hierarchy)
                    if nested:
                        symbol.children.append(nested)
                elif child.type in self.MEMBER_TYPES:
                    member = self._parse_member(child, src_bytes, lines, new_hierarchy)
                    if member:
                        symbol.children.append(member)

        return symbol

    def _parse_member(
            self,
            node,
            src_bytes: bytes,
            lines: List[str],
            parent_hierarchy: List[str],
    ) -> Optional[JavaSymbol]:
        """Parse a method, constructor, or field."""
        if node.type == "field_declaration":
            field_text, names = _get_field_declaration(node, src_bytes)
            name = ", ".join(names) if names else "field"
            signature = field_text.rstrip(";").strip()
        else:
            name = _get_node_name(node, src_bytes) or "anonymous"
            signature = _get_method_signature(node, src_bytes)

        annotations = _extract_annotations(node, src_bytes)
        javadoc = _get_preceding_comments(node, src_bytes, lines)
        full_text = _node_text(src_bytes, node)

        return JavaSymbol(
            node_type=node.type,
            name=name,
            full_text=full_text,
            signature=signature,
            annotations=annotations,
            javadoc=javadoc,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_hierarchy=parent_hierarchy,
        )


# ============================================================================
# JAVA CHUNKER
# ============================================================================

@dataclass
class JavaChunker:
    """
    Production-grade Java chunker with:
    - Hierarchical parsing (class → nested class → method)
    - Javadoc/comment preservation
    - Framework detection and tagging
    - Smart context injection
    - Micro-chunking for large symbols
    """

    name: str = "java"

    def __init__(self, token_budgeter: Optional[TokenBudgeter] = None):
        self.budgeter = token_budgeter or TokenBudgeter()
        self._parser: Optional[JavaParser] = None

    @property
    def parser(self) -> Optional[JavaParser]:
        """Lazy-load parser."""
        if self._parser is None and get_parser is not None:
            try:
                self._parser = JavaParser()
            except Exception:
                pass
        return self._parser

    def chunk(
            self,
            text: str,
            source_id: str,
            *,
            ext: str,
            config: ChunkingConfig,
            **kwargs: Any,
    ) -> List[Chunk]:
        """Chunk Java source code."""

        if not self.parser:
            return self._fallback_brace(text, source_id, ext, config, reason="no_parser")

        try:
            java_file = self.parser.parse(text)
        except Exception as e:
            return self._fallback_brace(text, source_id, ext, config, reason=f"parse_error:{e}")

        if not java_file.top_level_symbols:
            return self._fallback_brace(text, source_id, ext, config, reason="no_symbols")

        blocks: List[Block] = []

        # 1. Emit header/preamble block
        if config.include_source_preamble and java_file.raw_header:
            blocks.append(Block(
                java_file.raw_header,
                {
                    "kind": "preamble",
                    "lang": "java",
                    "level": config.parent_level_name,
                    "package": java_file.package,
                    "import_count": len(java_file.imports),
                }
            ))

        # 2. Process all symbols recursively
        for symbol in java_file.top_level_symbols:
            self._emit_symbol_blocks(
                symbol,
                blocks,
                source_id,
                config,
                file_header=java_file.raw_header,
                class_context="",
            )

        if not blocks:
            return self._fallback_brace(text, source_id, ext, config, reason="no_blocks")

        # 3. Pack blocks into chunks
        base_meta: Dict[str, Any] = {
            "source_id": source_id,
            "ext": ext,
            "lang": "java",
            "chunker": self.name,
            "package": java_file.package,
        }

        chunks: List[Chunk] = []
        blocks_to_pack = blocks

        # Separate preamble chunk if configured
        if config.separate_preamble_chunk and blocks and blocks[0].meta.get("kind") == "preamble":
            chunks.extend(
                self.budgeter.pack_blocks(
                    [blocks[0]],
                    source_id=source_id,
                    base_meta=dict(base_meta, preamble=True),
                    chunk_tokens=config.chunk_tokens,
                    overlap_tokens=0,
                    hard_cap_tokens=config.hard_cap_tokens,
                    max_symbol_blocks_per_chunk=1,
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

        # 4. Context injection for child chunks
        if config.include_context_in_children:
            chunks = self._inject_context(chunks, java_file, config)

        return chunks

    def _emit_symbol_blocks(
            self,
            symbol: JavaSymbol,
            blocks: List[Block],
            source_id: str,
            config: ChunkingConfig,
            file_header: str,
            class_context: str,
    ) -> None:
        """Recursively emit blocks for a symbol and its children."""

        # Build parent ID
        parent_id = f"{source_id}:java:{symbol.node_type}:{symbol.qualified_name}:{symbol.line_start}-{symbol.line_end}"

        # Base metadata for this symbol
        parent_meta: Dict[str, Any] = {
            "kind": "symbol",
            "node_type": symbol.node_type,
            "symbol": symbol.name,
            "qualified_name": symbol.qualified_name,
            "symbol_class": symbol.symbol_class,
            "lang": "java",
            "line_start": symbol.line_start,
            "line_end": symbol.line_end,
            "level": config.parent_level_name,
            "parent_id": parent_id,
            "annotations": symbol.annotations,
            "has_javadoc": bool(symbol.javadoc),
        }

        # Add framework metadata
        if symbol.frameworks:
            parent_meta["frameworks"] = symbol.frameworks

        # Determine text to emit
        # For classes with children, we might want to emit the class shell separately
        is_container = symbol.node_type in JavaParser.DECLARATION_TYPES and symbol.children

        if is_container:
            # Emit class header (without full body) as parent
            class_header = self._extract_class_header(symbol)

            if config.emit_parent_chunks:
                blocks.append(Block(class_header, dict(parent_meta, kind="class_header")))

            # Update class context for children
            new_class_context = class_header if not class_context else f"{class_context}\n\n{class_header}"

            # Process children
            for child in symbol.children:
                self._emit_symbol_blocks(
                    child,
                    blocks,
                    source_id,
                    config,
                    file_header=file_header,
                    class_context=new_class_context,
                )
        else:
            # Leaf symbol (method, field, etc.) or class without children
            text_to_chunk = symbol.full_text

            # Prepend Javadoc if available
            if symbol.javadoc and symbol.javadoc not in text_to_chunk:
                text_to_chunk = f"{symbol.javadoc}\n{text_to_chunk}"

            if config.emit_parent_chunks:
                blocks.append(Block(text_to_chunk, dict(parent_meta)))

            # Micro-chunk if hierarchical
            if config.hierarchical:
                micro_cap = config.micro_hard_cap_tokens or config.hard_cap_tokens
                parts = self.budgeter.split_text_micro(
                    text_to_chunk,
                    target_tokens=config.micro_chunk_tokens,
                    overlap_tokens=config.micro_overlap_tokens,
                    hard_cap_tokens=micro_cap,
                    strategy="lines",  # Always lines for code
                )

                for j, part in enumerate(parts):
                    child_meta = dict(parent_meta)
                    child_meta["kind"] = "symbol_child"
                    child_meta["level"] = config.child_level_name
                    child_meta["parent_id"] = parent_id
                    child_meta["child_index"] = j
                    # Store context for later injection
                    child_meta["_class_context"] = class_context
                    child_meta["_file_header"] = file_header
                    blocks.append(Block(part, child_meta))
            else:
                child_meta = dict(parent_meta)
                child_meta["kind"] = "symbol_child"
                child_meta["level"] = config.child_level_name
                child_meta["parent_id"] = parent_id
                child_meta["_class_context"] = class_context
                child_meta["_file_header"] = file_header
                blocks.append(Block(text_to_chunk, child_meta))

    def _extract_class_header(self, symbol: JavaSymbol) -> str:
        """Extract class declaration without the body content."""
        lines = symbol.full_text.splitlines()
        header_lines: List[str] = []
        brace_depth = 0
        found_open_brace = False

        for line in lines:
            header_lines.append(line)
            brace_depth += line.count("{")
            brace_depth -= line.count("}")

            if "{" in line and not found_open_brace:
                found_open_brace = True
                # Add placeholder for body
                if brace_depth > 0:
                    header_lines.append("    // ... members ...")
                    header_lines.append("}")
                break

        result = "\n".join(header_lines)

        # Prepend javadoc if available
        if symbol.javadoc:
            result = f"{symbol.javadoc}\n{result}"

        return result

    def _inject_context(
            self,
            chunks: List[Chunk],
            java_file: JavaFile,
            config: ChunkingConfig,
    ) -> List[Chunk]:
        """Inject file header and class context into child chunks."""
        out: List[Chunk] = []

        for chunk in chunks:
            bms = chunk.metadata.get("blocks_meta") or []
            is_child = any(
                isinstance(bm, dict) and bm.get("level") == config.child_level_name
                for bm in bms
            )

            if is_child:
                # Get context from first block's metadata
                class_context = ""
                file_header = java_file.raw_header

                for bm in bms:
                    if isinstance(bm, dict):
                        class_context = bm.get("_class_context", "")
                        file_header = bm.get("_file_header", file_header)
                        break

                # Build context prefix
                context_parts: List[str] = []
                if file_header:
                    context_parts.append(file_header)
                if class_context:
                    context_parts.append(class_context)

                if context_parts:
                    context = "\n\n".join(context_parts)
                    new_text = f"{context}\n\n// ... code ...\n\n{chunk.text}"
                    out.append(Chunk(id=chunk.id, text=new_text, metadata=chunk.metadata))
                else:
                    out.append(chunk)
            else:
                out.append(chunk)

        return out

    def _fallback_brace(
            self,
            text: str,
            source_id: str,
            ext: str,
            config: ChunkingConfig,
            reason: str,
    ) -> List[Chunk]:
        """Fallback to brace-based splitting when parsing fails."""
        # Extract header manually
        header = self._extract_header_manual(text, config.max_header_chars)

        # Split by braces
        parts = self._split_by_braces(text)
        blocks: List[Block] = []

        if header:
            blocks.append(Block(header, {"kind": "preamble", "lang": "java", "level": config.parent_level_name}))

        for i, part in enumerate(parts):
            parent_id = f"{source_id}:java:fallback:{i}"
            parent_meta = {
                "kind": "brace_block",
                "level": config.parent_level_name,
                "parent_id": parent_id,
                "lang": "java",
            }

            if config.emit_parent_chunks:
                blocks.append(Block(part, dict(parent_meta)))

            if config.hierarchical:
                micro = self.budgeter.split_text_micro(
                    part,
                    target_tokens=config.micro_chunk_tokens,
                    overlap_tokens=config.micro_overlap_tokens,
                    hard_cap_tokens=config.micro_hard_cap_tokens or config.hard_cap_tokens,
                    strategy="lines",
                )
            else:
                micro = [part]

            for j, mp in enumerate(micro):
                child_meta = dict(parent_meta)
                child_meta["kind"] = "brace_child"
                child_meta["level"] = config.child_level_name
                child_meta["parent_id"] = parent_id
                child_meta["child_index"] = j
                blocks.append(Block(mp, child_meta))

        if not blocks and text.strip():
            blocks = [Block(text.strip(), {"kind": "raw", "level": config.child_level_name, "lang": "java"})]

        base_meta = {
            "source_id": source_id,
            "ext": ext,
            "lang": "java",
            "chunker": f"{self.name}:fallback",
            "reason": reason,
        }

        chunks = self.budgeter.pack_blocks(
            blocks,
            source_id=source_id,
            base_meta=base_meta,
            chunk_tokens=config.chunk_tokens,
            overlap_tokens=config.overlap_tokens,
            hard_cap_tokens=config.hard_cap_tokens,
            chunk_id_prefix=f"{self.name}_fallback",
        )

        # Context injection for fallback
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

    def _extract_header_manual(self, text: str, max_chars: int) -> str:
        """Manually extract Java header (package, imports, class declaration)."""
        lines = text.splitlines()
        header_lines: List[str] = []

        i = 0
        # Skip leading whitespace/comments
        while i < len(lines) and not lines[i].strip():
            i += 1

        # Initial block comment/Javadoc
        if i < len(lines) and lines[i].lstrip().startswith("/*"):
            while i < len(lines):
                header_lines.append(lines[i])
                if "*/" in lines[i]:
                    i += 1
                    break
                i += 1

        # Package, imports, annotations, class declaration
        for line in lines[i:]:
            s = line.strip()
            if s.startswith("package ") or s.startswith("import "):
                header_lines.append(line)
            elif s.startswith("@"):
                header_lines.append(line)
            elif any(kw in s for kw in ("class ", "interface ", "enum ", "record ", "@interface ")):
                header_lines.append(line)
                break
            elif s and not s.startswith("//"):
                # Stop at other content
                if header_lines and not any(kw in header_lines[-1] for kw in ("package", "import", "@")):
                    break

        header = "\n".join(header_lines).strip()
        return header[:max_chars] if header else ""

    def _split_by_braces(self, text: str) -> List[str]:
        """Split text by matching braces (fallback)."""
        lines = text.splitlines()
        chunks: List[str] = []
        buf: List[str] = []
        depth = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if buf and depth == 0:
                    s = "\n".join(buf).strip()
                    if s:
                        chunks.append(s)
                    buf = []
                else:
                    buf.append(line)
                continue

            depth += stripped.count("{")
            depth -= stripped.count("}")
            buf.append(line)

            if depth == 0 and len(buf) >= 30:
                s = "\n".join(buf).strip()
                if s:
                    chunks.append(s)
                buf = []

        if buf:
            s = "\n".join(buf).strip()
            if s:
                chunks.append(s)

        return chunks