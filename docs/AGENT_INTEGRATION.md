# Ontogram — Agent Integration Guide

This guide explains how to connect local AI agents (**Antigravity**, **Pi**,
**OpenCode**, and custom scripts) to **Ontogram**, the hybrid memory service
based on Cognee core.

---

## 1. Any MCP Client (Antigravity, Claude Code, Cursor, Gemini CLI, …)

The Ontogram MCP server is **harness/agent-agnostic**: it runs as a long-lived
streamable-HTTP endpoint, so every MCP client connects the same way — by URL.
No per-agent process, no local venv required. Tools exposed: `remember`,
`recall`, `remember_status`, `forget`, `list_datasets`, `list_agents`.

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

### Closing the async loop

`remember` returns as soon as the daemon accepts the write; cognify (graph
building) continues in the background. To confirm indexing finished, call
`remember_status` with the same scope triple — it reports `indexing`, `ready`,
or `timeout` for recent jobs. When guaranteed indexing matters more than speed,
pass `wait=true` to `remember`.

### Forgetting memory

`forget(scope, project_id, session_id)` deletes an **entire** scoped dataset.
It deliberately refuses lenient fallbacks: session scope without ids or project
scope without `project_id` is rejected rather than silently deleting the global
dataset. There is no fact-level deletion — re-remember what should be kept.

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

## 1b. Foundry Project — Claude + OMP (Opencode) Harness

Foundry (`/builds/foundry`) is wired to Ontogram for both harnesses via the same MCP bridge. IPs differ by runtime location:

* **Host agents (Claude Code, Opencode TUI, Cursor on host):** `http://localhost:9481/mcp` — Ontogram publishes `127.0.0.1:9481` (`docker-compose.yml:12`).
* **Dockerized Foundry server (`infra/docker-compose.yml:112`):** `http://host.docker.internal:9481/mcp` — host gateway from inside compose.

### Claude Code (foundry)

`foundry/.mcp.json` (project-level, auto-discovered by Claude Code):
```json
{
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" },
    "cognee-memory-docker": { "type": "http", "url": "http://host.docker.internal:9481/mcp" }
  }
}
```
`.claude/settings.json` keeps the spec-gate hook; no change needed beyond `.mcp.json`. Verify:
```bash
curl -fsS http://localhost:9481/mcp | head  # 406 expected (MCP handshake)
curl -fsS http://localhost:9480/docs | head # 200
```

### OMP / Opencode Harness (foundry)

Opencode reads `opencode.jsonc` (project or `~/.config/opencode/opencode.jsonc`). Add the same servers:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" }
  }
}
```
For containers, use `host.docker.internal` as above. Tools are identical: `remember`/`recall` with `scope`/`project_id` (`foundry` for this repo):
```json
{ "text": "Foundry uses Postgres :5433 + Kestra :8080", "scope": "project", "project_id": "foundry" }
```

### Make agents actually use memory (both harnesses)

Copy `integrations/AGENTS_MEMORY.md` block into `foundry/CLAUDE.md` and `foundry/AGENTS.md` (both already exist — paste under your harness instructions). Optionally wire `memory_bootstrap.py` into session hooks:
```bash
# recall at session start
./integrations/memory_bootstrap.py recall --project-id foundry
# remember at checkpoint
./integrations/memory_bootstrap.py remember "Decided X because Y" --project-id foundry
```
Project scoping: `foundry` → `deck_foundry_memory`; `foundry:<session>` → `deck_foundry_<session>_memory`.

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
