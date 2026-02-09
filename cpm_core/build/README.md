# cpm_core/build - Build System

**Packet building orchestration with incremental caching.**

The build system transforms source directories into queryable context packets through chunking, embedding, and FAISS indexing with intelligent caching for fast incremental builds.

---

## Quick Start

```python
from cpm_core.build.builder import DefaultBuilder, DefaultBuilderConfig

config = DefaultBuilderConfig(
    model_name="jinaai/jina-embeddings-v2-base-code",
    max_seq_length=1024,
    lines_per_chunk=80,
    overlap_lines=10,
    version="1.0.0",
)

builder = DefaultBuilder(config)
manifest = builder.build(source="./docs", destination="./packets/my-docs")
```

---

## Architecture

```
Source Directory
       │
       ├─ Scan files (code/text)
       │
       ├─ Chunk content (line-based)
       │
       ├─ Check cache (hash-based)
       │     │
       │     ├─ Reuse cached vectors
       │     └─ Embed new chunks
       │
       ├─ Build FAISS index
       │
       ├─ Write outputs:
       │     ├─ docs.jsonl
       │     ├─ vectors.f16.bin
       │     ├─ faiss/index.faiss
       │     ├─ manifest.json
       │     └─ cpm.yml
       │
       └─ Optional: Archive packet
```

---

## DefaultBuilder

**Main builder implementation.**

### Configuration

```python
@dataclass(frozen=True)
class DefaultBuilderConfig:
    model_name: str = "jinaai/jina-embeddings-v2-base-code"
    max_seq_length: int = 1024
    lines_per_chunk: int = 80         # Chunk size in lines
    overlap_lines: int = 10           # Overlap between chunks
    version: str = "0.0.0"            # Packet version
    archive: bool = True              # Create tar.gz archive
    archive_format: str = "tar.gz"    # "tar.gz" or "zip"
    embed_url: str = "http://127.0.0.1:8876"
    timeout: float | None = None      # HTTP timeout
```

### API

```python
class DefaultBuilder(CPMAbstractBuilder):
    def __init__(
        self,
        config: DefaultBuilderConfig | None = None,
        embedder: Embedder | None = None,
    ):
        """
        Initialize builder.

        Args:
            config: Builder configuration
            embedder: Custom embedder (default: HttpEmbedder)
        """

    def build(
        self,
        source: str,
        *,
        destination: str | None = None,
    ) -> PacketManifest | None:
        """
        Build a context packet.

        Args:
            source: Source directory path
            destination: Output directory path

        Returns:
            PacketManifest on success, None on failure
        """
```

---

## Build Workflow

### 1. Source Scanning

Recursively scans source directory for supported file types:

**Code files:**
- `.py`, `.js`, `.ts`, `.tsx`, `.java`, `.kt`, `.go`, `.rs`, `.cpp`, `.c`, `.h`, `.cs`

**Text files:**
- `.md`, `.txt`, `.rst`

**Output:** List of `DocChunk` objects with:
- `id`: Unique chunk identifier (`path:index`)
- `text`: Chunk content
- `metadata`: `{"path": str, "ext": str}`

### 2. Chunking Strategy

Simple line-based chunking with overlap:

```python
def _chunk_text(text: str, *, lines_per_chunk: int, overlap_lines: int):
    lines = text.splitlines()
    step = lines_per_chunk - overlap_lines

    for start in range(0, len(lines), step):
        chunk_lines = lines[start:start + lines_per_chunk]
        yield "\n".join(chunk_lines)
```

**Example:**

```
File with 100 lines, lines_per_chunk=80, overlap_lines=10:

Chunk 1: lines 0-79
Chunk 2: lines 70-99 (10-line overlap with chunk 1)
```

### 3. Incremental Caching

**Cache Key:** SHA-256 hash of chunk text

**Cache Loading:**

1. Check if previous build exists (`manifest.json`, `docs.jsonl`, `vectors.f16.bin`)
2. Verify embedding model compatibility
3. Load chunk hashes and vectors from previous build
4. Build hash → vector mapping

**Cache Usage:**

- **Reused chunks**: Hash exists in cache → reuse vector
- **New chunks**: Hash not in cache → embed via API
- **Removed chunks**: Hash in cache but not in new set → ignored

**Stats reported:**

```
[cache] new_chunks=250 reused=200 to_embed=50 removed=25
```

### 4. Embedding

**HTTP Embedder:**

```python
class HttpEmbedder:
    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model_name: str,
        max_seq_length: int,
        normalize: bool,
        dtype: str,
        show_progress: bool,
    ) -> np.ndarray:
        """
        Embed texts via HTTP API.

        Returns:
            np.ndarray: Shape (N, dim), dtype float32
        """
```

**Request format:**

```json
POST /embed
{
  "model": "jinaai/jina-embeddings-v2-base-code",
  "texts": ["chunk 1", "chunk 2", ...],
  "options": {
    "max_seq_length": 1024,
    "normalize": true,
    "show_progress": true
  }
}
```

### 5. FAISS Indexing

```python
from cpm_core.packet.faiss_db import FaissFlatIP

db = FaissFlatIP(dim=768)
db.add(vectors)  # vectors: np.ndarray of shape (N, 768)
db.save("faiss/index.faiss")
```

Uses `IndexFlatIP` (Inner Product) for cosine similarity on normalized vectors.

### 6. Output Files

**docs.jsonl** - Chunk metadata:

```json
{"id": "README.md:0", "text": "# Project\n...", "hash": "abc123...", "metadata": {"path": "README.md", "ext": ".md"}}
{"id": "main.py:0", "text": "import sys\n...", "hash": "def456...", "metadata": {"path": "main.py", "ext": ".py"}}
```

**vectors.f16.bin** - Embeddings in float16:

```
Binary file: N × dim float16 values (row-major)
```

**faiss/index.faiss** - FAISS index:

```
Binary FAISS index (IndexFlatIP)
```

**manifest.json** - Packet metadata:

```json
{
  "schema_version": "1.0",
  "packet_id": "my-docs",
  "embedding": {
    "model": "jinaai/jina-embeddings-v2-base-code",
    "dim": 768,
    "dtype": "float16",
    "normalized": true,
    "max_seq_length": 1024
  },
  "counts": {
    "docs": 250,
    "vectors": 250
  },
  "incremental": {
    "enabled": true,
    "reused": 200,
    "embedded": 50,
    "removed": 25
  },
  "checksums": {
    "docs.jsonl": {"algo": "sha256", "value": "..."},
    "vectors.f16.bin": {"algo": "sha256", "value": "..."}
  }
}
```

**cpm.yml** - Human-readable metadata:

```yaml
cpm_schema: 1
name: my-docs
version: 1.0.0
description: /path/to/docs
tags: docs,cpm
entrypoints: query
embedding_model: jinaai/jina-embeddings-v2-base-code
embedding_dim: 768
embedding_normalized: true
created_at: 2024-01-15T10:30:00Z
```

---

## Usage Examples

### Example 1: Basic Build

```bash
cpm build --source ./docs --destination ./packets/docs-v1 \
  --model jinaai/jina-embeddings-v2-base-code \
  --version 1.0.0
```

### Example 1b: LLM Builder with Explicit Embedding Model

```bash
cpm build --source C:\path\to\repo --builder llm:cpm-llm-builder \
  --name repo-packet --version 0.0.1 \
  --model BAAI/bge-base-en-v1.5 \
  --embed-url http://127.0.0.1:8876
```

### Example 1c: Rebuild Packet to Regenerate vectors/faiss

```bash
cpm build --source C:\path\to\repo --builder llm:cpm-llm-builder \
  --name repo-packet --version 0.0.1 \
  --model BAAI/bge-base-en-v1.5 \
  --embed-url http://127.0.0.1:8876
```

### Example 1d: Migrate Embedder via Default Provider

```bash
# embed URL comes from .cpm/config/embeddings.yml default provider
cpm build --source C:\path\to\repo --builder llm:cpm-llm-builder \
  --name repo-packet --version 0.0.1 \
  --model intfloat/multilingual-e5-base
```

`--packet-version` is still supported as a compatibility alias.
`--source` and `--builder` remain required because packet chunking is builder-specific.

### Example 2: Programmatic Build

```python
from cpm_core.build.builder import DefaultBuilder, DefaultBuilderConfig

config = DefaultBuilderConfig(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    max_seq_length=512,
    lines_per_chunk=100,
    overlap_lines=15,
    version="2.0.0",
    archive=True,
)

builder = DefaultBuilder(config)
manifest = builder.build(
    source="/path/to/source",
    destination="/path/to/output"
)

if manifest:
    print(f"Built packet: {manifest.packet_id}")
    print(f"Docs: {manifest.counts['docs']}")
    print(f"Vectors: {manifest.counts['vectors']}")
    print(f"Reused: {manifest.incremental['reused']}")
```

### Example 3: Incremental Build

```bash
# First build
cpm build --source ./docs --destination ./packets/docs-v1

# Modify source files
echo "New content" >> ./docs/new-file.md

# Rebuild (reuses existing vectors)
cpm build --source ./docs --destination ./packets/docs-v1
```

Output shows cache stats:

```
[cache] enabled: cached_vectors=200 dim=768
[cache] new_chunks=201 reused=200 to_embed=1 removed=0
[embed] missing_vectors shape=(1, 768) dtype=float32
```

---

## Performance Characteristics

- **Scanning**: ~5000 files/second
- **Chunking**: ~2000 files/second
- **Embedding**: Depends on model and server (typically 100-1000 chunks/second)
- **FAISS indexing**: Sub-second for 100k vectors
- **Cache hit rate**: Typically 90%+ for small edits

---

## See Also

- [cpm_core/packet/README.md](../packet/README.md) - Packet data structures
- [cpm_builtin/README.md](../../cpm_builtin/README.md) - Built-in features
