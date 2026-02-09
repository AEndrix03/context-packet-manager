# cpm_builtin - Built-in Features

**Default implementations of commands, builders, chunkers, and utilities.**

`cpm_builtin` provides the standard feature implementations that ship with CPM, including language-aware chunking, embedding management, package operations, and build/query commands.

---

## Package Structure

```
cpm_builtin/
├── chunking/           # Language-aware chunking strategies
│   ├── base.py         # ChunkingStrategy protocol
│   ├── router.py       # ChunkerRouter (auto/multi mode)
│   ├── python_ast.py   # Python AST-based chunking
│   ├── java.py         # Java structure-aware chunking
│   ├── markdown.py     # Markdown header-aware chunking
│   ├── text.py         # Token-budget text chunking
│   ├── treesitter_generic.py  # Tree-sitter (40+ languages)
│   ├── brace_fallback.py      # Fallback for C-style braces
│   ├── token_budget.py        # Token counting utilities
│   └── schema.py       # Chunking data models
├── embeddings/         # Embedding management
│   ├── config.py       # EmbeddingProviderConfig, EmbeddingsConfigService
│   ├── connector.py    # HTTP embedding connector
│   └── cache.py        # Embedding result caching
├── packages/           # Package management
│   ├── manager.py      # PackageManager, PackageSummary
│   ├── layout.py       # Package directory structure
│   ├── versions.py     # Version parsing and comparison
│   └── io.py           # Package I/O utilities
├── build.py            # Build command implementation
├── query.py            # Query command implementation
├── pkg.py              # Package commands (list, use, prune)
└── embed.py            # Embedding commands (via cpm_cli/cli.py)
```

---

## Chunking System

### Overview

CPM provides multiple chunking strategies optimized for different content types:

| Chunker | File Types | Approach |
|---------|------------|----------|
| `python_ast` | `.py` | AST-based (function/class boundaries) |
| `java` | `.java` | Structure-aware (method scope) |
| `markdown` | `.md` | Header hierarchy preservation |
| `text` | `.txt`, `.rst` | Token-budget line chunking |
| `treesitter_generic` | 40+ languages | Tree-sitter parsing |
| `brace_fallback` | C-style | Brace-based fallback |

### ChunkerRouter

Automatically selects the best chunker for each file:

```python
from cpm_builtin.chunking.router import ChunkerRouter
from cpm_builtin.chunking.base import ChunkingConfig

router = ChunkerRouter(mode="auto")
config = ChunkingConfig(chunk_tokens=800, overlap_tokens=120)

# Automatically selects python_ast chunker for .py files
chunks = router.chunk(
    text=python_code,
    source_id="main.py",
    ext=".py",
    config=config,
)
```

**Modes:**

- `auto` - Select best chunker for each file (default)
- `multi` - Use multiple chunkers and merge results

**Extension Mapping:**

```python
EXTENSION_CHUNKER_MAP = {
    ".py": "python_ast",
    ".java": "java",
    ".md": "markdown",
    ".txt": "text",
    ".js": "treesitter_generic",
    ".ts": "treesitter_generic",
    # ... 40+ more
}
```

[See chunking/README.md for details](./chunking/README.md)

---

## Embedding System

### EmbeddingProviderConfig

YAML-based configuration for embedding providers:

```yaml
# .cpm/config/embeddings.yml
providers:
  - name: local-jina
    url: http://127.0.0.1:8876
    model: jinaai/jina-embeddings-v2-base-code
    dims: 768
    batch_size: 32
    timeout: 60
    default: true

  - name: remote-openai
    url: https://api.openai.com/v1
    model: text-embedding-ada-002
    dims: 1536
    auth:
      type: bearer
      token: ${OPENAI_API_KEY}
```

### HttpEmbeddingConnector

HTTP client for embedding servers:

```python
from cpm_builtin.embeddings.connector import HttpEmbeddingConnector
from cpm_builtin.embeddings.config import EmbeddingProviderConfig

provider = EmbeddingProviderConfig(
    name="local",
    url="http://127.0.0.1:8876",
    model="all-MiniLM-L6-v2",
    dims=384,
)

connector = HttpEmbeddingConnector(provider)

texts = ["Hello, world!", "Another text"]
vectors = connector.embed_texts(texts)
# Returns: np.ndarray shape (2, 384)
```

[See embeddings/README.md for details](./embeddings/README.md)

---

## Package Management

### PackageManager

Manages installed context packets with versioning:

```python
from cpm_builtin.packages.manager import PackageManager

manager = PackageManager(workspace_root=".cpm")

# List packages
summaries = manager.list_packages()
for summary in summaries:
    print(f"{summary.name}: {summary.versions}")
    print(f"  Pinned: {summary.pinned_version}")
    print(f"  Active: {summary.active_version}")

# Use (pin) a version
manager.use("my-package@1.2.0")

# Prune old versions (keep 2 latest)
removed = manager.prune("my-package", keep=2)
```

**Directory Structure:**

```
.cpm/
├── packages/
│   └── my-package/
│       ├── 1.0.0/
│       ├── 1.1.0/
│       └── 1.2.0/
├── state/
│   ├── pins/
│   │   └── my-package.yml    # Pinned version
│   └── active/
│       └── my-package.yml    # Active version
```

[See packages/README.md for details](./packages/README.md)

---

## Commands

### Build Command

```bash
cpm build --source ./docs --destination ./packets/docs-v1 \
  --model jinaai/jina-embeddings-v2-base-code \
  --version 1.0.0
```

```bash
# LLM builder with explicit embedding model
cpm build --source C:\path\to\repo --builder llm:cpm-llm-builder \
  --name repo-packet --version 0.0.1 \
  --model BAAI/bge-base-en-v1.5 \
  --embed-url http://127.0.0.1:8876
```

```bash
# Rebuild same packet/version to materialize vectors + faiss
cpm build --source C:\path\to\repo --builder llm:cpm-llm-builder \
  --name repo-packet --version 0.0.1 \
  --model BAAI/bge-base-en-v1.5 \
  --embed-url http://127.0.0.1:8876
```

```bash
# Migrate embedder/model without passing --embed-url
# (uses default provider from .cpm/config/embeddings.yml)
cpm build --source C:\path\to\repo --builder llm:cpm-llm-builder \
  --name repo-packet --version 0.0.1 \
  --model intfloat/multilingual-e5-base
```

`--packet-version` is still accepted as an alias for compatibility.
`--source` and `--builder` remain required because chunking is builder-dependent.

**Implementation:** `build.py`

**Features:**

- Source scanning with extension filtering
- Language-aware chunking (via ChunkerRouter)
- HTTP embedding with caching
- FAISS indexing
- Incremental builds
- Archive creation (tar.gz/zip)

### Query Command

```bash
cpm query --packet my-docs --query "authentication setup" -k 5
```

**Implementation:** `query.py`

**Features:**

- FAISS-based vector search
- Embedding on-the-fly
- Result ranking and filtering
- Query caching

### Package Commands

```bash
cpm pkg list                    # List installed packages
cpm pkg use my-package@1.2.0    # Pin version
cpm pkg prune my-package --keep 2  # Remove old versions
```

**Implementation:** `pkg.py`

---

## Configuration

### Chunking Configuration

```python
from cpm_builtin.chunking.base import ChunkingConfig

config = ChunkingConfig(
    chunk_tokens=800,              # Target chunk size (tokens)
    overlap_tokens=120,            # Overlap between chunks
    hard_cap_tokens=1024,          # Maximum chunk size
    include_source_preamble=True,  # Add source path to chunks
    hierarchical=True,             # Enable hierarchical chunking
    micro_chunk_tokens=220,        # Child chunk size
    emit_parent_chunks=False,      # Only emit children (FAISS-friendly)
)
```

### Embedding Configuration

```yaml
# .cpm/config/embeddings.yml
providers:
  - name: provider-name
    url: http://endpoint
    model: model-name
    dims: 768
    batch_size: 32
    timeout: 60
    default: true
    auth:
      type: bearer
      token: ${ENV_VAR}
```

---

## Architecture Patterns

### Strategy Pattern (Chunking)

Each chunker implements `BaseChunker` protocol:

```python
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
```

Router selects strategy based on file extension.

### Connector Pattern (Embeddings)

`HttpEmbeddingConnector` abstracts HTTP communication:

- Request formatting
- Authentication handling
- Retry logic
- Batching
- Response parsing

### Manager Pattern (Packages)

`PackageManager` encapsulates package operations:

- Version resolution (latest, pinned, explicit)
- Lifecycle management (install, use, prune, remove)
- Directory layout handling

---

## Testing

```bash
pytest cpm_builtin/chunking/
pytest cpm_builtin/embeddings/
pytest cpm_builtin/packages/
```

---

## See Also

- [cpm_builtin/chunking/README.md](./chunking/README.md) - Chunking strategies
- [cpm_builtin/embeddings/README.md](./embeddings/README.md) - Embedding system
- [cpm_builtin/packages/README.md](./packages/README.md) - Package management
- [cpm_core/build/README.md](../cpm_core/build/README.md) - Build system
