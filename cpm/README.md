# Context Packet Manager (CPM)

A Python-based service and command-line interface (CLI) designed for managing, building, and querying modular context
packets. It provides comprehensive tools for text chunking, embedding generation, vector storage with FAISS, and an
MCP (Model Context Protocol) server to facilitate Retrieval Augmented Generation (RAG) applications.

## Features

* **Modular Context Packet Management:** Define, build, publish, install, and manage context packets, each containing
  chunked documents, embeddings, and FAISS indices.
* **Flexible Text Chunking:** Supports a variety of chunking strategies including:
    * **Language-Specific:** Python AST (`python_ast.py`), Java (`java.py`), Markdown (`markdown.py`), and generic
      Tree-sitter (`treesitter_generic.py`) for structured code/text.
    * **General Purpose:** Generic text-based (`text.py`), token-budget aware (`token_budget.py`), and brace-matching
      fallback (`brace_fallback.py`) chunkers.
    * **Adaptive Routing:** Automatically selects the best chunker based on file type using `chunkers/router.py`.
* **Embedding Server (FastAPI):** A dedicated HTTP service for generating text embeddings using various models (e.g.,
  Sentence Transformers) with configurable options. This server is a dependency for packet building and querying.
* **FAISS Integration:** Efficient vector storage and similarity search using FAISS (Flat Inner Product index) for fast
  retrieval of relevant context within packets.
* **MCP (Model Context Protocol) Server:** Exposes `lookup` and `query` functionalities as interoperable tools, allowing
  other applications to interact with CPM's core features.
* **Comprehensive CLI (`cpm`):** A powerful command-line interface for end-to-end management of context packets and the
  associated services.
* **Dynamic Embedding Model Handling:** The embedding server can manage and expose multiple embedding models configured
  via `pool.yml`.
* **Configuration Management:** Utilizes `config.yml` for general settings and `pool.yml` for embedding model
  definitions, typically initialized via `cpm init`.
* **Health & Status Monitoring:** API endpoints for checking service health and model status of the embedding server.

## Installation

It is highly recommended to install this project within a Python virtual environment (`venv`).

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

2. **Install the project in editable mode:**
   This installs the project and its dependencies, making the `cpm` command available.
   ```bash
   pip install -e .
   ```

## Configuration

The `cpm` ecosystem relies on `config.yml` for general settings and `pool.yml` for embedding model definitions. You can
initialize default configuration files using the `cpm init` command. This command typically creates a `.cpm` directory (
or a specified root) with default configuration files.

1. **Initialize configuration files:**
   ```bash
   cpm init [--root .cpm]
   ```
   This command creates the default configuration directory and files.

   **Example `config.yml`:**
   ```yaml
   version: 1
   client:
     base_url: "http://127.0.0.1:8876" # URL for the embedding server
   server:
     host: "127.0.0.1"
     port: 8876
   paths:
     root: ".cpm" # Default root for CPM related files (pidfiles, etc.)
     pool_yml: ".cpm/pool.yml" # Embedding model definitions
     config_yml: ".cpm/config.yml" # Main CPM configuration
     state_dir: ".cpm/state"
     logs_dir: ".cpm/logs"
     cache_dir: ".cpm/cache"
   process:
     pid_file: ".cpm/state/embed-server.pid" # PID file for the detached embedding server
   logging:
     level: "info"

defaults:
request_timeout_s: 120
max_queue_per_model: 1000
max_inflight_global: 256
hot_reload:
enabled: true
```

    **Example `pool.yml`:**
    ```yaml
    version: 1
    models:
      - name: "jinaai/jina-embeddings-v2-base-en"
        type: "local_st"
        normalize: true
        max_seq_length: 512
        dtype: "float32"
        alias: "jina-en"
      - name: "my-remote-model"
        type: "http"
        base_url: "http://my-remote-embedder.com/embed"
        remote_model: "remote-model-id"
        timeout_s: 60
        alias: "remote-alias"
    ```

2. **Environment Variable for Config Path (Optional):**
   You can specify a custom path for your `config.yml` using the `CPM_CONFIG` environment variable or the `--config`flag
   for CLI commands.
   ```bash
   CPM_CONFIG=/path/to/my/config.yml cpm embed start-server
   ```

## Usage

The `cpm` command-line tool is used to manage context packets and associated services. Ensure your virtual environment
is activated before running these commands.

### General Packet Management Commands

* **`cpm init [--root .cpm]`**: Initializes the default `.cpm` configuration directory and files.
* **`cpm lookup [--cpm_dir .cpm] [--format text|jsonl] [--all-versions]`**: Lists installed context packets in the
  specified CPM directory.
* **`cpm query --packet <packet_name_or_path> --query <text> [-k 5] [--cpm_dir .cpm] [--no-cache] [--cache-refresh]`**:
  Queries an installed packet using the embedding server and FAISS to find relevant context.
* **
  `cpm build --input-dir <source_path> --packet-dir <output_path> [--model <model_name>] [--max-seq-length <length>] [--version <version>] [--archive] [--archive-format tar.gz|zip] [--timeout <seconds>]`
  **: Builds a context packet from source files by chunking, embedding, and indexing them.
* **`cpm publish --from <packet_dir> --registry <url> [--overwrite] [--yes]`**: Publishes a built packet to a remote
  registry.
* **`cpm install <spec> --registry <url> [--cpm_dir .cpm]`**: Installs a packet from a registry (e.g.,
  `packet-name@latest` or `packet-name@1.0.0`).
* **`cpm uninstall <spec> [--cpm_dir .cpm]`**: Uninstalls a packet or a specific version from the local CPM directory.
* **`cpm update <spec> --registry <url> [--cpm_dir .cpm] [--purge]`**: Updates an installed packet to a newer version
  from a registry.
* **`cpm use <spec> [--cpm_dir .cpm]`**: Pins a specific version of an installed packet as the active one without
  re-downloading.
* **`cpm list-remote <name> --registry <url> [--include-yanked] [--format text|json] [--sort-semantic]`**: Lists
  available versions of a packet on a remote registry.
* **`cpm prune <name> [--keep 1] [--cpm_dir .cpm]`**: Removes older local versions of a packet, keeping a specified
  number of the latest versions.
* **`cpm cache clear --packet <packet_name> [--cpm_dir .cpm]`**: Clears the query cache for a specific packet.

### Embedding Server Commands (`cpm embed ...`)

These commands manage the dedicated HTTP embedding server that provides embedding functionality to `cpm build` and
`cpm query`.

* **`cpm embed start-server [--host 127.0.0.1] [--port 8876] [--detach] [--log-level warning] [--cpm_dir .cpm]`**:Starts
  the embedding HTTP server. Use `--detach` to run in the background.
* **`cpm embed attach-server [--host 127.0.0.1] [--port 8876] [--log-level info]`**: Starts the server in the foreground
  for logging and debugging.
* **`cpm embed stop-server [--cpm_dir .cpm]`**: Stops a detached embedding server using its PID file.
* **`cpm embed status [--host 127.0.0.1] [--port 8876]`**: Checks the health and status of the embedding server,
  including loaded models.

### MCP Server Commands (`cpm mcp ...`)

These commands manage the Model Context Protocol (MCP) server, which exposes `cpm` functionalities (`lookup` and`query`)
as interoperable tools.

* **`cpm mcp serve`**: Starts the MCP server, typically communicating via standard I/O (stdio). This allows other
  MCP-compatible clients to interact with CPM's capabilities.

### MCP Tools API

The MCP server (`cpm mcp serve`) exposes specific functionalities as tools that can be invoked by MCP-compatible
clients. These tools are defined within `src/mcp/server.py`.

#### `lookup`

Lists installed context packets in a CPM folder.

**Parameters:**

* `cpm_dir` (string, optional): The path to the CPM root directory. Defaults to `.cpm` or `RAG_CPM_DIR` environment
  variable.

**Returns:**
A dictionary with the following structure:

```json
{
  "ok": true,
  "cpm_dir": "/path/to/cpm/dir",
  "packets": [
    {
      "name": "packet-name",
      "version": "1.0.0",
      "description": "Packet description",
      "tags": [
        "python",
        "cpm"
      ],
      "entrypoints": [
        "query"
      ],
      "dir_name": "packet-name@1.0.0",
      "path": "/path/to/cpm/dir/packet-name@1.0.0",
      "docs": 100,
      "vectors": 1000,
      "embedding_model": "jinaai/jina-embeddings-v2-base-en",
      "embedding_dim": 768,
      "embedding_normalized": true,
      "has_faiss": true,
      "has_docs": true,
      "has_manifest": true,
      "has_cpm_yml": true
    }
  ],
  "count": 1
}
```

#### `query`

Queries an installed packet using its FAISS index and the embedding server to find relevant context.

**Parameters:**

* `packet` (string, required): The packet folder name under `cpm_dir` OR a direct path to a packet folder.
* `query` (string, required): The text query string.
* `k` (integer, optional): The number of top-k results to return. Defaults to `5`.
* `cpm_dir` (string, optional): The path to the CPM root directory. Defaults to `.cpm` or `RAG_CPM_DIR` environment
  variable.
* `embed_url` (string, optional): Overrides the default embedding server URL. Defaults to `RAG_EMBED_URL` environment
  variable or `http://127.0.0.1:8876`.

**Returns:**
A dictionary with the following structure:

```json
{
  "ok": true,
  "packet": "packet-name",
  "packet_path": "/path/to/cpm/dir/packet-name@1.0.0",
  "query": "your search query",
  "k": 5,
  "embedding": {
    "model": "jinaai/jina-embeddings-v2-base-en",
    "max_seq_length": 512,
    "embed_url": "http://127.0.0.1:8876"
  },
  "results": [
    {
      "score": 0.85,
      "id": "chunk-id-1",
      "text": "Extracted relevant text chunk.",
      "metadata": {
        "path": "src/file.py",
        "ext": ".py"
      }
    }
    // ... more results
  ]
}
```

### API Usage Example (Embedding Server)

The embedding server, managed by `cpm embed`, exposes an API for generating embeddings.

#### Request Body Parameters for `/embed`

* **`model`** (string, **required**): The name or alias of the embedding model to use for generating embeddings.
    * Example: `"jina-en"` (as defined in `pool.yml`)
* **`texts`** (array of strings, **required**): A list of text strings for which embeddings are to be generated.
    * Example: `["Hello, world!", "This is a test sentence."]`
* **`options`** (object, optional): A dictionary of additional options that can influence the embedding generation
  process.

    * **Common `options` for `local_st` (Sentence Transformer) models:**
        * `normalize` (boolean): Whether to normalize the embeddings. (e.g., `true`, `false`)
        * `max_seq_length` (integer): Maximum sequence length for the input texts. (e.g., `384`)
        * `dtype` (string): Data type for the embeddings. (e.g., `"float32"`, `"float16"`)

#### Example `curl` command for `/embed`

```bash
curl -X POST "http://127.0.0.1:8876/embed" \
     -H "Content-Type: application/json" \
     -d {
           "model": "jina-en",
           "texts": ["Hello, world!", "This is a test sentence."],
           "options": {"normalize": true, "max_seq_length": 512}
         \}
```