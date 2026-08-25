# Ontogram Quickstart for Agents — running in ~5 minutes

Zero-install path for wiring **opencode**, **pi**, **Claude Code**,
**Cursor**, or any MCP-capable agent into persistent memory. (Detailed guides:
[SETUP_GUIDE.md](SETUP_GUIDE.md) · [AGENT_INTEGRATION.md](AGENT_INTEGRATION.md))

---

## Step 1 — Start Ontogram (once)

```bash
git clone https://github.com/BLANCO-11/Ontogram && cd Ontogram
cp .env.example .env
```

Edit `.env` → set `LLM_API_KEY` (+ `LLM_ENDPOINT` / `LLM_MODEL` if not using an OpenAI-compatible gateway). Then:

```bash
docker compose up -d --build
```

Verify: `curl -s http://localhost:9480/api/v1/datasets` returns `[]` (or your datasets).

> Changed `.env` later? `docker compose up -d --force-recreate`.

## Step 2 — Register the MCP server in your agent

The server is the same URL for every harness: **`http://localhost:9481/mcp`**

### opencode

```bash
opencode mcp add cognee-memory --url http://localhost:9481/mcp --type remote
```

or in `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": { "cognee-memory": { "type": "remote", "url": "http://localhost:9481/mcp", "enabled": true } }
}
```

### Claude Code

```bash
claude mcp add --transport http cognee-memory http://localhost:9481/mcp
```

### Cursor / other GUI clients (`~/.cursor/mcp.json` etc.)

```json
{
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" }
  }
}
```

### pi / terminal-only agents

Use the helper client:

```bash
./agent_client.py remember "First fact" --scope project --project-id myproj
./agent_client.py recall "what do you know?" --scope project --project-id myproj
```

## Step 3 — Make the agent actually use it (2 minutes, highest ROI)

Tools alone get ignored. Drop the memory protocol block from
[integrations/AGENTS_MEMORY.md](../integrations/AGENTS_MEMORY.md) into your
agent instructions file — `AGENTS.md`, `CLAUDE.md`, or `.cursorrules` — at the
repo root. It tells the agent to *recall at session start* and *remember
decisions as they happen*.

For harnesses with shell hooks, use the bootstrap script instead:

```bash
# session-start hook
./integrations/memory_bootstrap.py recall --project-id $(basename $PWD)

# session-end hook
./integrations/memory_bootstrap.py remember "$(cat <<EOF
Session summary: <paste what happened>
EOF
)" --project-id $(basename $PWD)
```

## Step 4 — Verify end-to-end

In your agent, say:

> Remember that this project prefers async-first APIs. Then recall why.

Expected: a `remember` tool call (~0.3 s), then a `recall` tool call returning
your fact. Check indexing status anytime with the `remember_status` tool.

---

## Scope cheat-sheet

| You're storing… | Call |
| :--- | :--- |
| User-level preference | `scope="global"` |
| Project decision / architecture note | `scope="project"`, `project_id="<slug>"` |
| Session scratchpad | `scope="session"`, + `session_id` |
| Wipe a project's memory | `forget(scope="project", project_id="<slug>")` |

## If something's off

| Symptom | Fix |
| :--- | :--- |
| Agent can't connect | Is the stack up? `docker compose ps` — ports must be published on `127.0.0.1` |
| Recall returns nothing | Cognify takes seconds; check `remember_status`. Also confirm same scope+project_id used for both remember and recall |
| Auth errors in logs | Your LLM key in `.env` is bad — fix and `--force-recreate` (see [SETUP_GUIDE.md Issue 5](SETUP_GUIDE.md)) |
| Exposing beyond localhost | Set `ONTOGRAM_TOKEN` and open the port mappings deliberately ([security model](SETUP_GUIDE.md#security-model)) |
