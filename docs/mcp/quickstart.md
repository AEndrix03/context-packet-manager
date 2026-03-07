# MCP Quickstart

## 1. Set Environment

```powershell
$env:REGISTRY="registry.local/project"
$env:CPM_ROOT=".cpm"
$env:EMBEDDING_URL="http://127.0.0.1:8876"
$env:EMBEDDING_MODEL="mixedbread-ai/mxbai-embed-large-v1"
```

## 2. Start MCP Server

```powershell
cpm mcp:serve
```

Optional one-shot overrides:

```powershell
cpm mcp:serve --registry registry.local/project --cpm-dir .cpm --embed-url http://127.0.0.1:8876 --embed-model mixedbread-ai/mxbai-embed-large-v1
```

## 3. Connect a Client

The server runs over **stdio** (default of `mcp.run()`), the standard transport for all MCP clients.

### Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "component-rag": {
      "command": "cpm",
      "args": ["mcp:serve"],
      "env": {
        "REGISTRY": "registry.local/project",
        "CPM_ROOT": ".cpm",
        "EMBEDDING_URL": "http://127.0.0.1:8876",
        "EMBEDDING_MODEL": "mixedbread-ai/mxbai-embed-large-v1"
      }
    }
  }
}
```

Restart Claude Desktop; the tools (`lookup`, `query`, `plan_from_intent`, `evidence_digest`) appear automatically.

### Claude Code (CLI)

```bash
claude mcp add component-rag \
  -e REGISTRY=registry.local/project \
  -e CPM_ROOT=.cpm \
  -e EMBEDDING_URL=http://127.0.0.1:8876 \
  -e EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1 \
  -- cpm mcp:serve
```

Verify with `claude mcp list`.

### OpenAI Codex CLI

Add to `~/.codex/config.toml`:

```toml
[[mcp_servers]]
name = "component-rag"
command = "cpm"
args = ["mcp:serve"]

[mcp_servers.env]
REGISTRY = "registry.local/project"
CPM_ROOT = ".cpm"
EMBEDDING_URL = "http://127.0.0.1:8876"
EMBEDDING_MODEL = "mixedbread-ai/mxbai-embed-large-v1"
```

### VS Code + GitHub Copilot (≥ 1.99)

Create `.vscode/mcp.json` in the workspace:

```json
{
  "servers": {
    "component-rag": {
      "type": "stdio",
      "command": "cpm",
      "args": ["mcp:serve"],
      "env": {
        "REGISTRY": "registry.local/project",
        "CPM_ROOT": ".cpm",
        "EMBEDDING_URL": "http://127.0.0.1:8876",
        "EMBEDDING_MODEL": "mixedbread-ai/mxbai-embed-large-v1"
      }
    }
  }
}
```

## 4. Recommended Tool Flow

1. `lookup` to get `pinned_uri`.
2. `query` using that `pinned_uri`.
3. Optionally use `plan_from_intent` or `evidence_digest`.
