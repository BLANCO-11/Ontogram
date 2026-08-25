# Ontogram — Agent Integration Guide

This guide explains how to connect local AI agents (**Antigravity**, **Pi**,
**OpenCode**, and custom scripts) to **Ontogram**, the hybrid memory service
based on Cognee core.

---

## 1. Any MCP Client (Antigravity, Claude Code, Cursor, Gemini CLI, …)

The Ontogram MCP server is **harness/agent-agnostic**: it runs as a long-lived
streamable-HTTP endpoint, so every MCP client connects the same way — by URL.
No per-agent process, no local venv required. Tools exposed: `remember`,
`recall`, `list_datasets`, `list_agents`.

### Scoped memory contract

`remember` and `recall` take a **scope triple** rather than a flat agent id:

| Scope | Dataset written/searched | Notes |
| :--- | :--- | :--- |
| `"global"` | `deck_global_memory` | Shared across all projects |
| `"project"` | `deck_<project-slug>_memory` | Pass `project_id` (slug) |
| `"session"` | `deck_<project-slug>_<session-slug>_memory` | Pass `project_id` **and** `session_id` |

Missing ids degrade leniently toward global, so always pass `project_id`
explicitly for project or session memory.

```json
// remember: store a project-scoped fact
{ "text": "We chose SQLite over Postgres for the edge build",
  "scope": "project", "project_id": "ontogram" }

// recall: search that same scope
{ "query": "which database did we choose?", "scope": "project", "project_id": "ontogram" }
```

### Registration (recommended — HTTP)
Add this block to your agent's MCP configuration. The server key stays
`cognee-memory` — it is the identifier already wired into `.mcp.json` and
existing client configs, so Ontogram keeps it for backwards compatibility:

```json
{
  "mcpServers": {
    "cognee-memory": {
      "type": "http",
      "url": "http://localhost:9481/mcp"
    }
  }
}
```

### Fallback — stdio
For clients that spawn a subprocess instead of connecting to a URL (requires the
local `.venv` on the same machine):

```json
{
  "mcpServers": {
    "cognee-memory": {
      "command": "/path/to/Ontogram/.venv/bin/python",
      "args": ["/path/to/Ontogram/cognee_mcp_server.py", "--transport", "stdio"],
      "env": { "COGNEE_API_URL": "http://localhost:9480" }
    }
  }
}
```

> [!NOTE]
> The `agent_client.py` helper (below) predates the scoped-memory contract and
> still targets legacy `<user_id>_memory` datasets. Prefer the MCP tools with
> the scope triple for new integrations.

---

## 2. Pi / OpenCode / Terminal CLI Integration

For terminal scripts or agents that support HTTP or CLI execution:

### Option A: Using `agent_client.py` Helper

```bash
# Ingest memory into Pi's private dataset
./agent_client.py remember "User prefers daily summary reports at 9 AM" --user-id pi

# Ingest memory into OpenCode's private dataset
./agent_client.py remember "Bug in parser fixed by handling null AST nodes" --user-id opencode

# Query memory from Knowledge Graph
./agent_client.py recall "What are user preferences?" --user-id pi
```

### Option B: HTTP REST API Calls

#### Store Memory (`POST /api/v1/remember`)
```bash
curl -X POST "http://localhost:9480/api/v1/remember" \
  -H "X-User-Id: pi" \
  -F "data=User prefers dark mode UI themes" \
  -F "datasetName=pi_memory" \
  -F "run_in_background=true"
```

#### Query Memory (`POST /api/v1/recall`)
```bash
curl -X POST "http://localhost:9480/api/v1/recall" \
  -H "X-User-Id: pi" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What theme does the user prefer?",
    "datasetName": "pi_memory"
  }'
```

---

## 3. Python Integration

Python-based agents can import `agent_client.py` as a module:

```python
from agent_client import remember, recall

# Ingest memory (returns in < 1s with async background cognify)
remember("Refactored database layer to use connection pooling", user_id="antigravity")

# Query Knowledge Graph
results = recall("What database changes were made?", user_id="antigravity")
print(results)
```
