<div align="center">

# 🎯 Context Packet Manager

**Transform your documentation and codebases into intelligent, queryable knowledge bases for RAG applications**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)

[Features](#-key-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [Plugins](#-plugin-system) • [Docs](#-documentation)

</div>

---

## 🚀 What is CPM?

CPM (Context Packet Manager) is a **modular Python framework** that transforms documentation, codebases, and
knowledge repositories into **chunked, embedded, FAISS-indexed** context packets optimized for Retrieval Augmented
Generation.

### Why CPM?

- 🔌 **Plugin Architecture** - Extend without modifying core code
- 🧩 **Language-Aware Chunking** - 40+ languages with AST/Tree-sitter parsing
- ⚡ **Incremental Builds** - Hash-based caching for blazing fast rebuilds
- 🤖 **Claude Desktop Integration** - Native MCP support for AI assistants
- 📦 **Package Management** - Versioned packets with semantic versioning
- 🎯 **Zero Config** - Intelligent defaults, works out of the box

---

## ✨ Key Features

### 🔌 Extensible Plugin System

Create custom commands, builders, and retrievers without touching core code. Plugins auto-discover from `.cpm/plugins/`
and integrate seamlessly with the CLI.

```bash
cpm plugin:list              # List loaded plugins
cpm my-plugin:custom-command # Your command, integrated
```

### 🧩 Intelligent Chunking for 40+ Languages

CPM automatically detects and applies the optimal chunking strategy for your content. Can't find the right chunker?
Use `--builder custom-builder` to plug in your own.

| Language                  | Strategy             | Approach                  |
|---------------------------|----------------------|---------------------------|
| **Python**                | AST-based            | Function/class boundaries |
| **Java**                  | Structure-aware      | Method scope preservation |
| **JavaScript/TypeScript** | Tree-sitter          | Syntax-aware parsing      |
| **Markdown**              | Header-based         | Hierarchy preservation    |
| **40+ more**              | Tree-sitter/Fallback | Universal coverage        |

**Fully extensible**: Implement your own builder for custom logic.

### ⚡ Incremental Building

Rebuild only what changed. SHA-256 hash-based caching reuses existing embeddings:

```bash
# First build: 250 chunks
[embed] missing_vectors shape=(250, 768)

# Edit one file, rebuild
[cache] new_chunks=251 reused=250 to_embed=1 removed=0
[embed] missing_vectors shape=(1, 768)
```

### 🤖 Claude Desktop Integration

Native Model Context Protocol (MCP) support. Expose your context packets as tools directly in Claude Desktop:

```json
{
  "mcpServers": {
    "cpm": {
      "command": "cpm",
      "args": [
        "mcp:serve"
      ]
    }
  }
}
```

Claude can now search your docs, code, and knowledge bases conversationally!

### 📦 Package Management

Versioned packets with semantic versioning, pinning, and pruning:

```bash
cpm pkg list                      # List installed packets
cpm pkg use my-packet@1.2.0       # Pin specific version
cpm pkg prune my-packet --keep 2  # Keep 2 latest versions
```

---

## 🏃 Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/AEndrix03/component-rag.git
cd component-rag

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install CPM
pip install -e .

# Install dev dependencies (optional)
pip install -e ".[dev]"  # black, ruff, mypy, pytest
```

### Initialize Workspace

```bash
# Create .cpm/ workspace structure
cpm init

# Verify installation
cpm doctor
```

### Configure OpenAI-Compatible Embeddings Adapter

Point CPM to an adapter exposing `POST /v1/embeddings`:

```bash
cpm embed add \
  --name adapter-local \
  --url http://127.0.0.1:8080 \
  --model text-embedding-3-small \
  --dims 768 \
  --set-default
```

Minimal `.cpm/config/embeddings.yml` example:

```yaml
default: adapter-local
providers:
  - name: adapter-local
    type: http
    url: http://127.0.0.1:8080
    model: text-embedding-3-small
    dims: 768
    http:
      path: /v1/embeddings
    hints:
      normalize: true
```

Supported hint headers sent by CPM connector:
- `X-Embedding-Dim`
- `X-Embedding-Normalize`
- `X-Embedding-Task`
- `X-Model-Hint`

See `cpm_builtin/embeddings/README.md` for full adapter spec, Docker Compose examples, and troubleshooting.

### Build Your First Packet

```bash
# Start embedding server (or use remote service)
# (See embedding server docs for setup)

# Build a context packet from your docs
cpm build \
  --source ./docs \
  --destination ./packets/my-docs \
  --model jinaai/jina-embeddings-v2-base-code \
  --version 1.0.0
```

### Build Scenarios

```bash
# 1) Standard build (default builder)
cpm build \
  --source ./docs \
  --name my-docs \
  --version 1.0.0 \
  --model jinaai/jina-embeddings-v2-base-code \
  --embed-url http://127.0.0.1:8876
```

```bash
# 2) LLM builder (explicit embedding model)
cpm build \
  --source C:\path\to\repo \
  --builder llm:cpm-llm-builder \
  --name repo-packet \
  --version 0.0.1 \
  --model BAAI/bge-base-en-v1.5 \
  --embed-url http://127.0.0.1:8876
```

```bash
# 3) Rebuild same packet/version to regenerate vectors + FAISS
# (useful if a previous run produced chunks/cache but no vectors/index)
cpm build \
  --source C:\path\to\repo \
  --builder llm:cpm-llm-builder \
  --name repo-packet \
  --version 0.0.1 \
  --model BAAI/bge-base-en-v1.5 \
  --embed-url http://127.0.0.1:8876
```

```bash
# 4) Migrate to a different embedder/model using workspace default provider
# (embed URL is resolved from .cpm/config/embeddings.yml default provider)
cpm build \
  --source C:\path\to\repo \
  --builder llm:cpm-llm-builder \
  --name repo-packet \
  --version 0.0.1 \
  --model intfloat/multilingual-e5-base
```

Notes:
- `--packet-version` remains supported as a compatibility alias, but `--version` is preferred.
- `--source` and `--builder` are still required for deterministic rebuilds: chunk generation depends on builder behavior and source content.

**Output:**

```
[scan] files_indexed=145 chunks_total=1250
[cache] enabled: cached_vectors=0 dim=768
[embed] missing_vectors shape=(1250, 768)
[faiss] ntotal=1250
[done] build ok
```

### Query Your Packet

```bash
# Query for relevant context (auto-detects retriever from project config)
cpm query \
  --packet my-docs \
  --query "authentication setup" \
  -k 5

# Or specify a custom retriever
cpm query --packet my-docs --query "auth" --retriever custom-retriever
```

### Use with Claude Desktop

1. **Configure Claude Desktop**

   Edit `~/.config/Claude/claude_desktop_config.json` (Linux) or equivalent:

   ```json
   {
     "mcpServers": {
       "cpm": {
         "command": "/path/to/.venv/bin/cpm",
         "args": ["mcp:serve"],
         "env": {
           "RAG_CPM_DIR": "/path/to/workspace/.cpm"
         }
       }
     }
   }
   ```

2. **Restart Claude Desktop**

3. **Use in conversation:**
   ```
   You: "What packets are available?"
   Claude: [calls lookup tool] I can see 3 context packets...

   You: "Search my-docs for authentication examples"
   Claude: [calls query tool] Here are the relevant sections...
   ```

---

## 🏗️ Architecture

CPM follows a modular, plugin-based architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                         CPM                            │
└─────────────────────────────────────────────────────────────┘

         cpm_cli                     CLI Entry Point
            │
            ├─ Command Resolution
            └─ Token Parsing
                    │
                    ▼
         ┌──────────────────────┐
         │     cpm_core         │   Foundation Layer
         │                      │
         │  • CPMApp            │   Application Bootstrap
         │  • FeatureRegistry   │   Command/Plugin Registry
         │  • PluginManager     │   Plugin Discovery/Loading
         │  • Workspace         │   .cpm/ Management
         │  • EventBus          │   Lifecycle Hooks
         │  • ServiceContainer  │   Dependency Injection
         └──────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌──────────┐
  │ Plugins │ │Builtins │ │  Build   │
  │         │ │         │ │  System  │
  │ • MCP   │ │• Init   │ │• Chunker │
  │ • ...   │ │• Doctor │ │• Embedder│
  └─────────┘ └─────────┘ │• FAISS   │
                           └──────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │  Context Packet   │
                    │                   │
                    │  • docs.jsonl     │
                    │  • vectors.f16    │
                    │  • faiss/index    │
                    │  • manifest.json  │
                    └───────────────────┘
```

### Package Structure

```
component-rag/
├── cpm_core/           🏗️  Foundation layer (app, plugins, registry)
├── cpm_cli/            🖥️  CLI routing and command resolution
├── cpm_builtin/        🧰  Built-in features (chunking, embeddings, packages)
└── cpm_plugins/        🔌  Official plugins (MCP, etc.)
```

**[📚 See Architecture Docs](./DOCUMENTATION.md) for detailed component documentation**

---

## 🔌 Plugin System

CPM is built for extensibility. Create custom commands without touching core code.

### Create a Plugin in 3 Steps

**1. Create plugin directory:**

```bash
mkdir -p .cpm/plugins/my-plugin
cd .cpm/plugins/my-plugin
```

**2. Create `plugin.toml`:**

```toml
[plugin]
id = "my-plugin"
name = "My Custom Plugin"
version = "1.0.0"
entrypoint = "entrypoint:register_plugin"
```

**3. Create `entrypoint.py`:**

```python
from cpm_core.api import CPMAbstractCommand, cpmcommand
from cpm_core.plugin import PluginContext


@cpmcommand(name="hello", group="my-plugin")
class HelloCommand(CPMAbstractCommand):
    """Say hello to the user."""

    def configure(self, parser):
        parser.add_argument("--name", default="World")

    def run(self, args):
        print(f"Hello, {args.name}!")
        return 0


def register_plugin(ctx: PluginContext):
    ctx.logger.info("My plugin loaded!")
```

**4. Use your plugin:**

```bash
cpm my-plugin:hello --name CPM
# Output: Hello, CPM!
```

**[📖 Plugin Development Guide](./cpm_core/plugin/README.md)**

---

## 🧩 Intelligent Chunking

CPM automatically detects and selects the optimal chunking strategy for your content. If the default doesn't fit,
simply implement your own builder and pass `--builder your-builder` during build.

### Supported Strategies

| Chunker                | Languages                             | Key Feature                         |
|------------------------|---------------------------------------|-------------------------------------|
| **python_ast**         | Python                                | Preserves function/class boundaries |
| **java**               | Java                                  | Maintains method scope              |
| **treesitter_generic** | JS, TS, Go, Rust, C/C++, and 35+ more | Syntax tree parsing                 |
| **markdown**           | Markdown, reStructuredText            | Header hierarchy                    |
| **text**               | Plain text                            | Token-budget with overlap           |
| **brace_fallback**     | C-style languages                     | Brace-based sectioning              |

### Extensibility at Every Level

**Builders**: CPM intelligently selects builders based on project structure. Need custom logic?

```bash
cpm build --source ./docs --builder my-custom-builder
```

**Retrievers**: Auto-detected from project configuration, or explicitly specified:

```bash
cpm query --packet my-docs --query "search" --retriever my-custom-retriever
```

**Hierarchical Chunking**: Built-in support for multi-level chunking:

```python
config = ChunkingConfig(
    hierarchical=True,
    chunk_tokens=800,  # Parent chunk size
    micro_chunk_tokens=220,  # Child chunk size
    emit_parent_chunks=False,  # Only index children
)
```

**[📖 Chunking Documentation](./cpm_builtin/chunking/README.md)**

---

## 🤖 MCP Integration

CPM includes a built-in **Model Context Protocol** plugin for seamless Claude Desktop integration.

### MCP Tools

#### `lookup` - List Packets

```json
{
  "name": "lookup",
  "description": "List available context packets",
  "inputSchema": {
    "type": "object",
    "properties": {
      "cpm_dir": {
        "type": "string",
        "optional": true
      }
    }
  }
}
```

#### `query` - Semantic Search

```json
{
  "name": "query",
  "description": "Search context packets for relevant information",
  "inputSchema": {
    "type": "object",
    "properties": {
      "packet": {
        "type": "string",
        "required": true
      },
      "query": {
        "type": "string",
        "required": true
      },
      "k": {
        "type": "number",
        "default": 5
      }
    }
  }
}
```

### Integration Example

```javascript
// Claude Desktop config
{
  "mcpServers": {
    "cpm": {
      "command": "cpm",
      "args": ["mcp:serve"],
      "env": {
        "RAG_CPM_DIR": "/path/to/.cpm",
        "RAG_EMBED_URL": "http://127.0.0.1:8876"
      }
    }
  }
}
```

**Conversation with Claude:**

```
User: Search my python-stdlib packet for file I/O examples

Claude: [Calls query tool]
Here are the most relevant sections from python-stdlib:

1. **File Operations (score: 0.92)**
   "The `open()` function is the primary way to work with files..."

2. **Context Managers (score: 0.89)**
   "Using `with open()` ensures proper file closure..."
```

**[📖 MCP Plugin Documentation](./cpm_plugins/mcp/README.md)**

---

## 📦 Built-in Commands

| Command                     | Description                            |
|-----------------------------|----------------------------------------|
| `cpm init`                  | Initialize CPM workspace               |
| `cpm doctor`                | Validate workspace and diagnose issues |
| `cpm build`                 | Build a context packet from source     |
| `cpm pkg list`              | List installed packets                 |
| `cpm pkg use <pkg@version>` | Pin a packet version                   |
| `cpm pkg prune <pkg>`       | Remove old packet versions             |
| `cpm plugin:list`           | List loaded plugins                    |
| `cpm plugin:doctor`         | Diagnose plugin issues                 |
| `cpm mcp:serve`             | Start MCP server for Claude            |

**[📖 Command Reference](./cpm_cli/README.md)**

---

## ⚙️ Configuration

### Environment Variables

| Variable         | Purpose                  | Default                      |
|------------------|--------------------------|------------------------------|
| `RAG_CPM_DIR`    | Workspace root directory | `.cpm`                       |
| `RAG_EMBED_URL`  | Embedding server URL     | `http://127.0.0.1:8876`      |
| `CPM_CONFIG`     | Main config file path    | `.cpm/config/cpm.toml`       |
| `CPM_EMBEDDINGS` | Embeddings config path   | `.cpm/config/embeddings.yml` |

### Workspace Structure

```
.cpm/
├── packages/           # Installed context packets
│   └── <name>/
│       └── <version>/
├── config/             # Configuration files
│   ├── cpm.toml        # Main configuration
│   └── embeddings.yml  # Embedding providers
├── plugins/            # Workspace plugins
├── cache/              # Query result caches
├── state/              # Runtime state (pins, active versions)
├── logs/               # Application logs
└── pins/               # Version pin files
```

---

## 📚 Documentation

CPM includes comprehensive documentation for every component:

### 📖 Core Documentation

- **[cpm_core](./cpm_core/README.md)** - Foundation layer architecture
- **[cpm_core/api](./cpm_core/api/README.md)** - Extension interfaces
- **[cpm_core/plugin](./cpm_core/plugin/README.md)** - Plugin system deep dive
- **[cpm_core/registry](./cpm_core/registry/README.md)** - Feature registry
- **[cpm_core/build](./cpm_core/build/README.md)** - Build system internals
- **[cpm_core/packet](./cpm_core/packet/README.md)** - Packet data structures

### 🧰 Built-in Features

- **[cpm_builtin/chunking](./cpm_builtin/chunking/README.md)** - Chunking strategies
- **[cpm_builtin/embeddings](./cpm_builtin/embeddings/README.md)** - Embedding management
- **[cpm_builtin/packages](./cpm_builtin/packages/README.md)** - Package management

### 🔌 Plugins

- **[cpm_plugins/mcp](./cpm_plugins/mcp/README.md)** - MCP plugin for Claude Desktop

### 🗺️ Navigation

- **[DOCUMENTATION.md](./DOCUMENTATION.md)** - Complete documentation index

---

## 🛠️ Development

### Prerequisites

- Python 3.11+
- Virtual environment recommended

### Setup Development Environment

```bash
# Clone and install
git clone https://github.com/AEndrix03/component-rag.git
cd component-rag
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=cpm_core --cov=cpm_builtin --cov=cpm_cli

# Run specific test file
pytest tests/test_core.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Format code
black .

# Lint
ruff check .

# Type check
mypy .
```

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Write tests** for new functionality
4. **Ensure code quality** (black, ruff, mypy pass)
5. **Commit with clear messages** (`git commit -m 'Add amazing feature'`)
6. **Push to your fork** (`git push origin feature/amazing-feature`)
7. **Open a Pull Request**

### Development Guidelines

- Follow [PEP 8](https://peps.python.org/pep-0008/) style guide
- Use type hints for all functions
- Write docstrings for public APIs
- Add tests for bug fixes and new features
- Update documentation for user-facing changes

---

## 📊 Performance

### Build Performance

- **Scanning**: ~5,000 files/second
- **Chunking**: ~2,000 files/second (language-dependent)
- **Incremental builds**: 90%+ cache hit rate for small edits

### Query Performance

- **FAISS search**: Sub-millisecond on 100k vectors
- **Scalability**: Tested with 10M+ vector indices
- **Memory**: ~4KB per vector (768-dim float32)

---

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Built with [FAISS](https://github.com/facebookresearch/faiss) for efficient vector search
- Uses [Sentence Transformers](https://www.sbert.net/) for embeddings
- Tree-sitter integration for multi-language parsing
- FastMCP for Model Context Protocol support

---

<div align="center">

**[⬆ Back to Top](#-context-packet-manager)**

Made with ❤️ for Everyone

</div>

## OCI Packaging

CPM supports packaging packets for standard OCI registries (Harbor, GHCR, GitLab, Nexus OCI compatible).

- Packet tag mapping: `name@version -> <registry>/<project>/<name>:<version>`
- Immutable identity: always consume by digest (`@sha256:...`) after resolve
- OCI staging layout includes:
  - `packet.manifest.json`
  - `packet.lock.json` (when present)
  - `payload/` (`cpm.yml`, `manifest.json`, `docs.jsonl`, `vectors.f16.bin`, `faiss/index.faiss`)

Digest form example:

```text
registry.local/project/demo@sha256:<digest>
```

## OCI Install and Publish

Example publish/install/query flow with OCI registries:

```bash
# Publish a built packet directory
cpm publish --from-dir ./dist/demo/1.0.0 --registry registry.local/project

# Install from OCI by name@version
cpm install demo@1.0.0 --registry registry.local/project

# Query uses selected model from install lock when available
cpm query --packet demo --query "authentication setup" -k 5
```

For Harbor, use the project/repository form in `--registry`, for example:

```text
harbor.local/my-project
```
