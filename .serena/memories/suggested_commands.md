# Suggested Commands (Windows / PowerShell)
# Environment setup
- `python -m venv .venv`
- `.venv\Scripts\activate`
- `pip install -e ./cpm` (or `./embedding_pool`, `./registry`)

# CPM core
- `cpm init`
- `cpm build --input-dir ./docs --packet-dir ./packets/example --model jina-en --version 1.0.0`
- `cpm query --packet example --query "..." -k 5`
- `cpm publish --from ./packets/my-knowledge-base --registry http://localhost:8786`
- `cpm install my-knowledge-base@1.0.0 --registry http://localhost:8786`

# Embedding server
- `cpm embed register --model jinaai/jina-embeddings-v2-base-en --type local_st --max-seq-length 512 --normalize --alias jina-en`
- `cpm embed start-server --detach`
- `cpm embed status`

# Registry server
- `cpm-registry start --detach`
- `cpm-registry status`

# MCP server
- `cpm mcp serve`

# Tests
- `pytest`

# Useful PowerShell utilities
- `Get-ChildItem` (list files)
- `Get-ChildItem -Recurse` (recursive list)
- `Select-String -Pattern "..." -Path **\*.py` (search)
- `Set-Location` / `cd` (change directory)