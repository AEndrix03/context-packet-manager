# Embedding Pool Server

A FastAPI-based service designed for managing and serving text embedding models. It provides a flexible interface to integrate various embedding models, including local Sentence Transformers and remote HTTP services, and offers a command-line interface for easy administration.

## Features

*   **FastAPI Backend:** High-performance, asynchronous API for efficient embedding generation and model management.
*   **Flexible Model Integration:** Supports both local Sentence Transformer models and integration with remote embedding services via HTTP.
*   **Dynamic Model Management:** Register, enable, disable, and unregister embedding models dynamically without restarting the server.
*   **Model Aliasing:** Assign user-friendly aliases to your registered models for easier access.
*   **Scalability & Queuing:** Configurable scaling for model replicas and robust request queuing to handle varying loads.
*   **CLI Tool (`embedpool`):** A comprehensive command-line interface for initializing the configuration, starting/stopping the server, and managing models.
*   **Configuration Management:** Utilizes `config.yml` for server settings and `pool.yml` to define registered embedding models.
*   **Health & Status Monitoring:** Dedicated API endpoints for checking service health and retrieving detailed status of deployed models.

## Installation

It is highly recommended to install this project within a Python virtual environment (`venv`).

1.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    # On Windows:
    .venv\Scripts\activate
    # On macOS/Linux:
    source .venv/bin/activate
    ```

2.  **Install the project in editable mode:**
    This installs the project and its dependencies, making the `embedpool` command available.
    ```bash
    pip install -e .
    ```

## Configuration

The `embedding_pool` server is configured using a `config.yml` file for global settings and a `pool.yml` file for model definitions. You can initialize default configuration files using the `embedpool init` command.

1.  **Initialize configuration files:**
    ```bash
    embedpool init
    ```
    This command creates a `.config` directory with `config.yml` and `pool.yml` files.

    **Example `config.yml`:**
    ```yaml
    version: 1
    client:
      base_url: "http://127.0.0.1:8876"
    server:
      host: "127.0.0.1"
      port: 8876
    paths:
      root: ".config"
      pool_yml: ".config/pool.yml"
      config_yml: ".config/config.yml"
      state_dir: ".config/state"
      logs_dir: ".config/logs"
      cache_dir: ".config/cache"
    process:
      pid_file: ".config/state/pool.pid"
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
    models: []
    ```

2.  **Environment Variable for Config Path (Optional):**
    You can specify a custom path for your `config.yml` using the `EMBEDPOOL_CONFIG` environment variable or the `--config` flag for CLI commands.
    ```bash
    EMBEDPOOL_CONFIG=/path/to/my/config.yml embedpool pool start
    ```

## Usage

The `embedpool` command-line tool is used to manage the embedding pool server and its models. Ensure your virtual environment is activated before running these commands.

*   **Initialize configuration files:**
    ```bash
    embedpool init [--root .config]
    ```
    Creates the default configuration directory and files.

*   **Start the server in the foreground:**
    ```bash
    embedpool pool start [--config .config/config.yml]
    ```
    Press `CTRL+C` to stop the server.

*   **Start the server in the background (detached mode):
    ```bash
    embedpool pool start --detach [--config .config/config.yml]
    ```
    This will run the server as a background process. The PID will be stored in `config.yml`'s `pid_file` path (default: `.config/state/pool.pid`).

*   **Stop the background server:**
    ```bash
    embedpool pool stop [--config .config/config.yml]
    ```
    This command reads the PID from the configured `pid_file` and terminates the corresponding process.

*   **Check the server status:**
    ```bash
    embedpool pool status [--config .config/config.yml]
    ```
    Reports whether the server is running and provides details about registered models.

*   **Check server health:**
    ```bash
    embedpool pool health [--config .config/config.yml]
    ```
    A quick check to see if the server is responsive.

*   **Register a local Sentence Transformer model:**
    ```bash
    embedpool register --model sentence-transformers/all-MiniLM-L6-v2 --type local_st \
      --max-seq-length 384 --normalize --dtype float32 --alias minilm-l6
    ```

*   **Register a remote HTTP embedding service:**
    ```bash
    embedpool register --model my-remote-embedding-model --type http \
      --base-url "http://localhost:5000/embed" --remote-model "model-id-on-remote" \
      --timeout-s 60 --alias remote-model-alias
    ```

*   **Set or clear a model alias:**
    ```bash
    # Set an alias
    embedpool set-alias --model sentence-transformers/all-MiniLM-L6-v2 --alias mini-lm

    # Clear an alias
    embedpool set-alias --model mini-lm --alias ""
    ```

*   **Enable or disable a model:**
    ```bash
    # Enable a model
    embedpool enable --model mini-lm

    # Disable a model
    embedpool disable --model mini-lm
    ```

*   **Unregister a model:**
    ```bash
    embedpool unregister --model mini-lm
    ```

### API Usage Example (Embedding)

Once the server is running and models are registered, you can send requests to the `/embed` endpoint.

#### Request Body Parameters for `/embed`

*   **`model`** (string, **required**): The name or alias of the embedding model to use for generating embeddings.
    *   Example: `"minilm-l6"`
*   **`texts`** (array of strings, **required**): A list of text strings for which embeddings are to be generated.
    *   Example: `["Hello, world!", "This is a test sentence."]`
*   **`options`** (object, optional): A dictionary of additional options that can influence the embedding generation process. The available options are specific to the registered model and its driver type.

    *   **Common `options` for `local_st` (Sentence Transformer) models:**
        *   `normalize` (boolean): Whether to normalize the embeddings. (e.g., `true`, `false`)
        *   `max_seq_length` (integer): Maximum sequence length for the input texts. (e.g., `384`)
        *   `dtype` (string): Data type for the embeddings. (e.g., `"float32"`, `"float16"`)

    *   **Common `options` for `http` (remote service) models:**
        *   These options depend entirely on the remote embedding service's API. Refer to the documentation of your remote service for available options.

    *   Example with options:
        ```json
        {
           "model": "minilm-l6",
           "texts": ["Another example."],
           "options": {
             "normalize": true,
             "max_seq_length": 128
           }
        }
        ```

#### Example `curl` command for `/embed`

```bash
curl -X POST "http://127.0.0.1:8876/embed" \
     -H "Content-Type: application/json" \
     -d '{
           "model": "minilm-l6",
           "texts": ["Hello, world!", "This is a test sentence."],
           "options": {}
         }'
```