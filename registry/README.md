# CPM Registry - Package Registry Server

A lightweight, self-hosted package registry server designed for managing and serving packages, leveraging S3-compatible
storage for package artifacts.

## Features

* **S3-Compatible Storage:** Utilizes any S3-compatible object storage (e.g., AWS S3, MinIO) for storing package files.
* **FastAPI Backend:** Built with FastAPI for high performance and easy API development.
* **Lightweight Database:** Uses SQLite for metadata storage.
* **CLI Management:** Simple command-line interface (`cpm`) for starting, stopping, and managing the registry server.
* **Environment-based Configuration:** Easy configuration through `.env` files.

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

The registry server is configured using environment variables, typically managed via a `.env` file in the project root.

1. **Create a `.env` file:**
   Copy the example `.env` file provided or create one manually in the root of the project:
   ```
   # Registry server
   REGISTRY_HOST=127.0.0.1
   REGISTRY_PORT=8786
   REGISTRY_DB_PATH=./registry.db

   # S3 / MinIO Configuration
   # Replace with your S3-compatible storage details
   REGISTRY_BUCKET_URL=http://localhost:9000/ # e.g., MinIO endpoint, or leave empty for AWS S3
   REGISTRY_BUCKET_NAME=cpm-registry
   REGISTRY_S3_REGION=us-east-1
   REGISTRY_S3_ACCESS_KEY=your_access_key
   REGISTRY_S3_SECRET_KEY=your_secret_key

   # Optional: Public base URL if behind a proxy or for external access
   # REGISTRY_PUBLIC_BASE_URL=http://your.domain.com:8787
   ```

2. **Set S3 Credentials:**
   Ensure `REGISTRY_S3_ACCESS_KEY` and `REGISTRY_S3_SECRET_KEY` are set in your `.env` file or as system environment
   variables. These are crucial for the registry to connect to your S3-compatible storage.

## Usage

The `cpm` command-line tool is used to manage the registry server. Ensure your virtual environment is activated before
running these commands.

* **Start the server in the foreground:**
  ```bash
  cpm start
  ```
  Press `CTRL+C` to stop the server.

* **Start the server in the background (detached mode):**
  ```bash
  cpm start --detach
  ```
  This will run the server as a background process. Logs will be written to `.registry.log` and the process ID to
  `.registry.pid` in the project root.

* **Stop the background server:**
  ```bash
  cpm stop
  ```
  This command reads the PID from `.registry.pid` and terminates the corresponding process.

* **Check the server status:**
  ```bash
  cpm status
  ```
  Reports whether the server is running or stopped.

* **Specify a custom `.env` file:**
  If your `.env` file is not in the project root or has a different name, you can specify its path:
  ```bash
  cpm start --env-file /path/to/my/.env
  ```
