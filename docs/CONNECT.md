# Ontogram — End-to-End Connect & Use

One container, two ports, any harness. No separate frontend — just the REST daemon (`:9480`) and the MCP bridge (`:9481/mcp`).

---

## 1. Up the service

```bash
# clone (if needed)
git clone https://github.com/BLANCO-11/Ontogram && cd Ontogram

# config — provider-agnostic, any OpenAI-compatible (opencode-go, OpenAI, etc.)
cp .env.example .env
# edit .env: set LLM_API_KEY (and LLM_ENDPOINT if not OpenAI direct)
# Working opencode-go example (chat, verified):
#   LLM_PROVIDER="openai"
#   LLM_MODEL="openai/deepseek-v4-flash"
#   LLM_ENDPOINT="https://opencode.ai/zen/go/v1"   # base only; LiteLLM appends /chat/completions
#   # muse-spark-1.2-contributor via direct curl: https://opencode.ai/zen/go/v1/responses

# build + run (single container: REST :9480 + MCP :9481)
docker compose up -d --build
docker compose logs -f   # Ctrl-C to detach

# verify (10s)
curl -fsS http://localhost:9480/docs | head -n 1          # 200
docker ps | grep cognee_hybrid_service                     # Up (healthy)
docker compose exec cognee_hybrid_service python /app/manage_llm.py --status
docker compose exec cognee_hybrid_service python /app/manage_llm.py --test   # direct OpenAI-compatible 200
```

All memory persists on `cognee_data:/cognee-storage` — `docker compose down` safe; `down -v` deletes.

Ports (`docker-compose.yml:12`):
* `127.0.0.1:9480` → REST API + Swagger `http://localhost:9480/docs` + visualizer `http://localhost:9480/api/v1/visualize`
* `127.0.0.1:9481` → MCP bridge `http://localhost:9481/mcp` (streamable-HTTP)

Inside Docker, replace `localhost` with `host.docker.internal` (e.g. `http://host.docker.internal:9481/mcp`).

---

## 2. Connect any harness

The MCP bridge is **harness-agnostic** — one HTTP URL for every client. Tools: `remember`, `recall`, `remember_status`, `forget`, `list_datasets`, `list_agents`. Scoped via `scope`/`project_id`/`session_id` → `deck_*_memory`.

### Generic (any MCP client)

```json
{
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" }
  }
}
```
See `mcp_config_example.json`.

### Claude Code (Claude TUI)

Project auto-discovers `foundry/.mcp.json:2`:

```json
{
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" },
    "cognee-memory-docker": { "type": "http", "url": "http://host.docker.internal:9481/mcp" }
  }
}
```

Or via CLI (project or global):

```bash
cd /path/to/your-project   # e.g. builds/foundry
claude mcp add ontogram --transport http http://localhost:9481/mcp
claude mcp list            # verify
# then in TUI: /mcp  -> remember/recall
```

Restart Claude after adding.

### Opencode / OMP Harness

Project `opencode.json` (or `opencode.jsonc`) — auto-discovered:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" }
  }
}
```

Or via CLI (no `--type` flag):

```bash
cd /path/to/your-project
opencode mcp add ontogram --url http://localhost:9481/mcp
# for dockerized servers also:
opencode mcp add ontogram-docker --url http://host.docker.internal:9481/mcp
opencode mcp list
```

Global is `~/.config/opencode/opencode.jsonc:1`; project is `opencode.json` in repo root.

### Cursor / Pi / Antigravity / Gemini CLI

Same URL — point your MCP client at `http://localhost:9481/mcp` (or `host.docker.internal` from containers). See `docs/AGENT_INTEGRATION.md`.

---

## 3. Use (remember / recall)

### Via MCP (preferred — scoped)

```json
// store project fact
{ "text": "We chose Postgres :5433 for Foundry; Kestra :8080", "scope": "project", "project_id": "foundry" }
// recall
{ "query": "which database does Foundry use?", "scope": "project", "project_id": "foundry" }
```

Scopes: `global` → `deck_global_memory`, `project` → `deck_<project>_memory`, `session` → `deck_<project>_<session>_memory`. Always pass `project_id` for project/session.

### Via shell hooks (no MCP)

```bash
# session start: print stored context
./integrations/memory_bootstrap.py recall --project-id foundry
# checkpoint: store summary
./integrations/memory_bootstrap.py remember "Decided X because Y" --project-id foundry
```

### Via REST (curl)

```bash
# store (async, <1s)
curl -X POST http://localhost:9480/api/v1/remember \
  -H "X-User-Id: foundry" -F "data=We use SQLite for edge" -F "datasetName=deck_foundry_memory" -F "run_in_background=true"

# recall
curl -X POST http://localhost:9480/api/v1/recall \
  -H "Content-Type: application/json" -H "X-User-Id: foundry" \
  -d '{"query":"which DB?","datasets":["deck_foundry_memory"]}'

# status (async indexing)
curl "http://localhost:9480/api/v1/datasets" | jq
```

### Via `agent_client.py` (legacy `<user_id>_memory`)

```bash
./agent_client.py remember "Build uses pnpm" --user-id foundry
./agent_client.py recall "what build tool?" --user-id foundry
```

---

## 4. Make agents actually use it — Discover-or-Create (use if available else create)

Agents must not assume memory exists. Use `integrations/ensure_memory.py` for idempotent "discover existing md file + Ontogram graph, or create one" — safe to run at every session start from any harness (Claude, Opencode, Cursor). No venv needed (uses `requests` or stdlib).

```bash
# discover existing ONTGRAM.md + deck_foundry_memory, or create both if neither exists
python integrations/ensure_memory.py --project-id foundry --md-file ONTGRAM.md --api-url http://localhost:9480
# from inside foundry/:
python ../deployments/Ontogram/integrations/ensure_memory.py --project-id foundry --md-file ONTGRAM.md
# custom path:
python integrations/ensure_memory.py --project-id foundry --md-file docs/ONTGRAM.md --project-root /path/to/foundry
```

Behavior (idempotent):
1. Checks local md file (`ONTGRAM.md`) and Ontogram `deck_foundry_memory` via `POST /api/v1/recall`
2. `Both exist` → merges recalled hits into md file (no duplicate `remember`)
3. `Only Ontogram` → materializes md file from recall hits (`Created ... from Ontogram`)
4. `Only md file` → pushes md content to Ontogram (`Pushed ... to Ontogram`)
5. `Neither` → creates md template + seeds Ontogram (`Created ... + seeded`)

Verified: `foundry/ONTGRAM.md` now mirrors `deck_foundry_memory` (2.3K, synced), `testproj123` template 518B. Subsequent runs merge.

Hook it into your harness so it runs automatically:
* **Claude Code** (`.claude/settings.json` hooks or `CLAUDE.md` instruction): run `ensure_memory.py --project-id foundry` at `SessionStart`
* **Opencode** (`opencode.json` hooks): `session_start` → `python integrations/ensure_memory.py --project-id foundry`

Fallback: copy `integrations/AGENTS_MEMORY.md` block into `CLAUDE.md` / `AGENTS.md` / `.cursorrules` — it tells the agent to `recall` at session start and `remember` durable facts as they happen (decisions, bug fixes, preferences).

---

## 5. Foundry wiring (example)

`builds/foundry` has both:
* `foundry/.mcp.json:2` → Claude
* `foundry/opencode.json:2` → Opencode/OMP

Host agents use `localhost:9481`, dockerized `server` (`infra/docker-compose.yml:132`) uses `host.docker.internal:9481`. Project scoping: `foundry` → `deck_foundry_memory`.

---

## Troubleshooting

* `curl http://localhost:9481/mcp` → `400`/`406` is normal for bare GET; MCP needs JSON-RPC POST. Check `http://localhost:9480/docs` → 200 and `opencode mcp list` / `claude mcp list`.
* LiteLLM logs: Cognee uses LiteLLM library internally even with any OpenAI-compatible base — `manage_llm.py --test` now does direct `requests` first (no LiteLLM proxy needed). Any `https://.../v1` base works.
* Go `muse-spark-1.2-contributor` is `https://opencode.ai/zen/go/v1/responses` (direct `curl` 200, chat 500) — use `deepseek-v4-flash`/`glm` via `https://opencode.ai/zen/go/v1/chat/completions` for Cognee memory; use `muse-spark` in TUI via `opencode-go/muse-spark-1.2-contributor`.
