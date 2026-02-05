# Context Packet Manager (CPM)

**A comprehensive ecosystem for building, managing, and serving modular context packets for Retrieval Augmented
Generation (RAG) applications.**

CPM is a Python-based framework that transforms your documentation, codebases, and text corpora into efficient,
queryable knowledge bases. It provides end-to-end tooling for chunking, embedding, indexing, and retrieving contextual
information through a modular architecture.

---

## Architecture Overview

The CPM ecosystem consists of three integrated components:

### 1. CPM Core (Context Packet Manager)

The main CLI and service for creating, managing, and querying context packets. Each packet is a self-contained knowledge
module containing chunked documents, vector embeddings, and FAISS indices optimized for fast semantic search.

### 2. Embedding Pool Server

A high-performance FastAPI service that manages and serves multiple embedding models. Provides a unified interface for
generating text embeddings using local Sentence Transformers or remote HTTP services, with dynamic model registration
and scalability features.

### 3. CPM Registry

A lightweight, self-hosted package registry for publishing, versioning, and distributing context packets across teams
and projects. Leverages S3-compatible storage for efficient artifact management.

---

## Key Features

### Context Packet Management

- **Modular Knowledge Bases**: Encapsulate domain-specific knowledge into versioned, reusable packets
- **Advanced Chunking Strategies**: Language-aware chunkers for Python, Java, Markdown, and generic text with AST-based
  parsing
- **FAISS Integration**: Efficient vector similarity search with optimized indexing
- **Version Control**: Full semantic versioning support with update, rollback, and pruning capabilities
- **MCP Protocol Support**: Expose packet querying as interoperable tools for AI applications

### Embedding Infrastructure

- **Multi-Model Support**: Run multiple embedding models simultaneously with automatic load balancing
- **Flexible Backends**: Support for local Sentence Transformers and remote embedding services
- **Dynamic Management**: Register, enable, disable models without server restarts
- **Model Aliasing**: User-friendly names for quick model access
- **Queue Management**: Robust request queuing with configurable concurrency limits

### Distribution & Collaboration

- **Self-Hosted Registry**: Complete control over your knowledge base distribution
- **S3-Compatible Storage**: Works with AWS S3, MinIO, or any S3-compatible backend
- **Semantic Versioning**: Proper version management with yanked version support
- **Team Sharing**: Publish and install packets across development teams

---

## Installation

All three components follow the same installation pattern. It's recommended to use a Python virtual environment:

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install CPM Core
pip install -e .

# Install Embedding Pool (in separate repository)
pip install -e ./embedding-pool

# Install CPM Registry (in separate repository)
pip install -e ./cpm-registry
```

---

## Quick Start

### 1. Bootstrap the workspace and sanity-check the environment

```bash
cpm init
cpm doctor
```

`cpm doctor` verifies the workspace layout, validates `.cpm/config/embeddings.yml`, reports plugin status, shows the configured registry endpoint, and prints quick alias hints for the legacy commands that still live under `cpm/src/cli`.

### 2. Register an embedding provider (legacy alias)

```bash
cpm embed add \
  --name local-encoder \
  --type http \
  --url http://127.0.0.1:8876 \
  --model jinaai/jina-embeddings-v2-base-en \
  --dims 768
```

Embedding commands such as `cpm embed add/start-server/status` currently delegate to the helper under `cpm_cli/cli.py`, keeping the provider management flow stable while the new `cpm_core` command surface evolves. The example above updates the `.cpm/config/embeddings.yml` that `cpm doctor` monitors.

### 3. Start an embedding server

Use your preferred embedding server (for instance the local `embedding_pool` service):

```bash
cpm embed start-server --detach
```

### 4. Build a context packet

```bash
cpm build --source ./docs --destination ./packets/my-knowledge-base \
  --model jinaai/jina-embeddings-v2-base-en --embed-url http://127.0.0.1:8876 --packet-version 1.0.0
```

You can point `--embed-url` to any service that exposes the `/embed` and `/health` endpoints; `embedding_pool` is a recommended local option.

### 5. Query the packet (legacy alias)

```bash
cpm query --packet my-knowledge-base --query "authentication setup" -k 5
```

This command routes through the legacy CLI so the old query interface stays available while the new MCP-powered flow evolves.

### 6. Publish and install via the registry

```bash
cpm-registry start --detach
cpm publish --from ./packets/my-knowledge-base --registry http://localhost:8786
cpm install my-knowledge-base@1.0.0 --registry http://localhost:8786
```

`cpm publish/install` still use the legacy registry client, so the new CLI simply reuses the old, proven behavior but now lives inside the `cpm_core` feature registry.

---

## Legacy Compatibility

The root `cpm` executable is backed by `cpm_core`, while the familiar legacy commands still work. Embedding commands (`cpm embed ...`) are routed through the helper defined in `cpm_cli/cli.py`, and the other legacy tokens (`query`, `publish`, `install`, `prune`, etc.) are forwarded to the parser under `cpm/src/cli`, so your scripts continue to behave as before.

`cpm doctor` surfaces that alias table alongside workspace tips: it warns if it finds artifacts in the legacy `.cpm/<packet>` layout and shows how the modern `.cpm/packages`, `.cpm/config`, and `.cpm/state` hierarchy is structured.

## Configuration

### CPM Core Configuration

**`config.yml`** - Main configuration file:

```yaml
version: 1
client:
  base_url: "http://127.0.0.1:8876"
server:
  host: "127.0.0.1"
  port: 8876
paths:
  root: ".cpm"
  pool_yml: ".cpm/pool.yml"
  state_dir: ".cpm/state"
  logs_dir: ".cpm/logs"
  cache_dir: ".cpm/cache"
process:
  pid_file: ".cpm/state/embed-server.pid"
logging:
  level: "info"
defaults:
  request_timeout_s: 120
  max_queue_per_model: 1000
  max_inflight_global: 256
hot_reload:
  enabled: true
```

**`pool.yml`** - Embedding model definitions:

```yaml
version: 1
models:
  - name: "jinaai/jina-embeddings-v2-base-en"
    type: "local_st"
    normalize: true
    max_seq_length: 512
    dtype: "float32"
    alias: "jina-en"
  - name: "custom-remote-model"
    type: "http"
    base_url: "http://my-embedder.com/embed"
    remote_model: "model-v1"
    timeout_s: 60
    alias: "custom-model"
```

### Registry Configuration

**`.env`** file for CPM Registry:

```bash
# Registry server
REGISTRY_HOST=127.0.0.1
REGISTRY_PORT=8786
REGISTRY_DB_PATH=./registry.db

# S3 Configuration
REGISTRY_BUCKET_URL=http://localhost:9000/
REGISTRY_BUCKET_NAME=cpm-registry
REGISTRY_S3_REGION=us-east-1
REGISTRY_S3_ACCESS_KEY=your_access_key
REGISTRY_S3_SECRET_KEY=your_secret_key

# Optional: Public URL
# REGISTRY_PUBLIC_BASE_URL=http://your.domain.com:8786
```

---

## Advanced Usage

### Language-Specific Chunking

CPM automatically selects optimal chunking strategies based on file types:

- **Python**: AST-based chunking preserving function and class boundaries
- **Java**: Structure-aware parsing maintaining method scope
- **Markdown**: Header-hierarchy respecting chunks
- **Generic Code**: Tree-sitter powered parsing for 40+ languages
- **Plain Text**: Token-budget aware chunking with semantic boundaries

### Model Context Protocol (MCP) Integration

CPM can be integrated with Claude and other MCP-compatible clients to provide context retrieval capabilities directly
within AI conversations.

#### Starting the MCP Server

```bash
# Start MCP server (stdio mode for Claude integration)
cpm mcp serve
```

Available MCP tools:

- `lookup`: List installed context packets
- `query`: Search packets for relevant context

#### Claude Desktop Integration

To integrate CPM with Claude Desktop, add the following configuration to your Claude config file:

**Location of Claude config file:**

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**Configuration example:**

```json
{
  "mcpServers": {
    "context-packet-manager": {
      "command": "C:/path/to/context-packet-manager/cpm/.venv/Scripts/cpm.exe",
      "args": [
        "mcp",
        "serve"
      ],
      "env": {
        "RAG_CPM_DIR": "C:/path/to/context-packet-manager/.cpm",
        "RAG_EMBED_URL": "http://127.0.0.1:8876"
      }
    }
  }
}

```

**Platform-specific Python paths:**

**Windows:**

```json
"command": "C:/path/to/your/project/.venv/Scripts/python.exe"
```

**macOS/Linux:**

```json
"command": "/path/to/your/project/.venv/bin/python"
```

**Configuration parameters:**

- `command`: Full path to Python interpreter in your virtual environment
- `args`: Arguments to launch the MCP server module
- `env.PYTHONPATH`: Path to your CPM source directory
- `env.RAG_CPM_DIR`: Path to your `.cpm` directory containing installed packets
- `env.RAG_EMBED_URL`: URL of your embedding server (must be running)

**Complete setup example:**

1. Install CPM and activate virtual environment
2. Start embedding server:
   ```bash
   cpm embed start-server --detach
   ```
3. Build or install context packets
4. Add MCP configuration to Claude config file
5. Restart Claude Desktop

Once configured, Claude will have access to your context packets through the `lookup` and `query` tools. You can ask
Claude to search your documentation, code, or any indexed content directly in conversation.

**Example usage in Claude:**

```
User: Search my project documentation for authentication setup
Claude: [Uses query tool to search relevant packet]
```

### Dynamic Model Management

```bash
# Register new model at runtime
cpm embed register --model sentence-transformers/all-MiniLM-L6-v2 \
  --type local_st --alias minilm

# Enable/disable models
cpm embed enable --model minilm
cpm embed disable --model minilm

# Set or update aliases
cpm embed set-alias --model minilm --alias mini-lm-v6

# Unregister models
cpm embed unregister --model mini-lm-v6
```

### Package Lifecycle Management

```bash
# Check available versions on registry
cpm list-remote my-packet --registry http://localhost:8786

# Update to latest version
cpm update my-packet --registry http://localhost:8786

# Pin specific version
cpm use my-packet@1.2.0

# Remove old versions (keep 2 latest)
cpm prune my-packet --keep 2

# Clear query cache
cpm cache clear --packet my-packet
```

---

## API Reference

### Embedding Server API

**POST** `/embed`

Generate embeddings for text inputs.

```bash
curl -X POST "http://127.0.0.1:8876/embed" \
     -H "Content-Type: application/json" \
     -d '{
           "model": "jina-en",
           "texts": ["Hello, world!", "Another text to embed"],
           "options": {
             "normalize": true,
             "max_seq_length": 512
           }
         }'
```

**Response:**

```json
{
  "embeddings": [
    [
      0.1,
      0.2,
      ...
    ],
    [
      0.3,
      0.4,
      ...
    ]
  ],
  "model": "jinaai/jina-embeddings-v2-base-en",
  "dimension": 768
}
```

**GET** `/health`

Check server health and model status.

**GET** `/status`

Detailed information about loaded models and server configuration.

### MCP Protocol Tools

#### `lookup` Tool

List installed context packets.

**Parameters:**

- `cpm_dir` (optional): CPM root directory path

**Returns:**

```json
{
  "ok": true,
  "cpm_dir": "/path/to/.cpm",
  "packets": [
    {
      "name": "my-knowledge-base",
      "version": "1.0.0",
      "description": "Documentation for project X",
      "tags": [
        "docs",
        "api"
      ],
      "docs": 250,
      "vectors": 5000,
      "embedding_model": "jinaai/jina-embeddings-v2-base-en",
      "embedding_dim": 768
    }
  ],
  "count": 1
}
```

#### `query` Tool

Search packet for relevant context.

**Parameters:**

- `packet` (required): Packet name or path
- `query` (required): Search query text
- `k` (optional): Number of results (default: 5)
- `cpm_dir` (optional): CPM root directory
- `embed_url` (optional): Override embedding server URL

**Returns:**

```json
{
  "ok": true,
  "packet": "my-knowledge-base",
  "query": "authentication setup",
  "k": 5,
  "results": [
    {
      "score": 0.89,
      "id": "chunk-42",
      "text": "To configure authentication, add the following...",
      "metadata": {
        "path": "docs/auth.md",
        "ext": ".md"
      }
    }
  ]
}
```

---

## Command Reference

### CPM Core Commands

| Command           | Description                         |
|-------------------|-------------------------------------|
| `cpm init`        | Initialize configuration directory  |
| `cpm lookup`      | List installed packets              |
| `cpm query`       | Search packet for context           |
| `cpm build`       | Create new context packet           |
| `cpm publish`     | Publish packet to registry          |
| `cpm install`     | Install packet from registry        |
| `cpm uninstall`   | Remove installed packet             |
| `cpm update`      | Update packet to newer version      |
| `cpm use`         | Pin specific packet version         |
| `cpm list-remote` | Show available versions on registry |
| `cpm prune`       | Remove old packet versions          |
| `cpm cache clear` | Clear query cache                   |

### Embedding Pool Commands

| Command                  | Description            |
|--------------------------|------------------------|
| `cpm embed start-server` | Start embedding server |
| `cpm embed stop-server`  | Stop background server |
| `cpm embed status`       | Check server health    |
| `cpm embed register`     | Register new model     |
| `cpm embed enable`       | Enable model           |
| `cpm embed disable`      | Disable model          |
| `cpm embed set-alias`    | Set model alias        |
| `cpm embed unregister`   | Remove model           |

### Registry Commands

| Command               | Description           |
|-----------------------|-----------------------|
| `cpm-registry start`  | Start registry server |
| `cpm-registry stop`   | Stop registry server  |
| `cpm-registry status` | Check registry status |

### MCP Server Commands

| Command         | Description               |
|-----------------|---------------------------|
| `cpm mcp serve` | Start MCP protocol server |

---

## Use Cases

### Documentation Search

Build searchable knowledge bases from technical documentation, API references, and internal wikis. Enable developers to
quickly find relevant information without manual searching.

### Codebase Understanding

Index entire codebases with language-aware chunking. Query for implementation examples, design patterns, or specific
functionality across millions of lines of code.

### Customer Support

Create context packets from support articles, FAQs, and product documentation. Power chatbots and support tools with
accurate, up-to-date information.

### Research & Analysis

Index research papers, articles, and reports. Quickly retrieve relevant passages for literature reviews, competitive
analysis, or market research.

### Team Knowledge Sharing

Publish curated knowledge packets to internal registries. Ensure consistent access to company standards, best practices,
and institutional knowledge.

### AI-Assisted Development

Integrate with Claude Desktop to provide AI assistants with direct access to your project documentation, codebases, and
knowledge repositories during development conversations.

---

## Performance Characteristics

### Chunking Performance

- **Python AST**: ~1000 files/second
- **Markdown**: ~2000 files/second
- **Generic Text**: ~5000 files/second

### Embedding Server

- **Throughput**: Depends on model and hardware
- **Queue Management**: 1000 requests/model default
- **Concurrent Processing**: Configurable replica scaling

### Vector Search

- **FAISS Flat IP**: Sub-millisecond queries on 100k vectors
- **Scalability**: Tested with 10M+ vector indices
- **Memory**: ~4KB per vector (768-dim float32)

---

## Environment Variables

| Variable                 | Description           | Default                 |
|--------------------------|-----------------------|-------------------------|
| `CPM_CONFIG`             | Path to config.yml    | `.cpm/config.yml`       |
| `RAG_CPM_DIR`            | CPM root directory    | `.cpm`                  |
| `RAG_EMBED_URL`          | Embedding server URL  | `http://127.0.0.1:8876` |
| `EMBEDPOOL_CONFIG`       | Embedding pool config | `.cpm/config.yml`       |
| `REGISTRY_BUCKET_URL`    | S3 endpoint URL       | -                       |
| `REGISTRY_S3_ACCESS_KEY` | S3 access key         | -                       |
| `REGISTRY_S3_SECRET_KEY` | S3 secret key         | -                       |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                     CPM Ecosystem                        │
└─────────────────────────────────────────────────────────┘

    ┌──────────────┐         ┌──────────────┐
    │  Source Code │         │  Documents   │
    │   /docs      │         │   /wiki      │
    └──────┬───────┘         └──────┬───────┘
           │                        │
           └────────┬───────────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │    cpm build        │
         │  (Chunking Engine)  │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Embedding Pool     │
         │  Server (FastAPI)   │
         │  Multiple Models    │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Context Packet     │
         │  chunks/ + faiss/   │
         │  + manifest.json    │
         └──────────┬──────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────┐      ┌──────────────────┐
│ cpm query    │      │  cpm publish     │
│ (Local Use)  │      │  to Registry     │
└──────┬───────┘      └────────┬─────────┘
       │                       │
       │                       ▼
       │            ┌─────────────────────┐
       │            │   CPM Registry      │
       │            │   (S3 + SQLite)     │
       │            └─────────┬───────────┘
       │                      │
       │                      ▼
       │            ┌─────────────────────┐
       │            │   cpm install       │
       │            │   (Team Access)     │
       │            └─────────────────────┘
       │
       └──────────► MCP Integration
                    (Claude Desktop, etc.)
```

---

## Contributing

We welcome contributions to all components of the CPM ecosystem!!!

---

## Support

For issues, questions, or feature requests:

- Open an issue on GitHub
- Check existing documentation
- Review example configurations

---

**Built with Python, FastAPI, FAISS, and Sentence Transformers**
