# Ontogram — Hybrid Memory Service for Local AI Agents

> **Ontogram**: based on Cognee core.

[![Ontogram](https://img.shields.io/badge/ontogram-hybrid--memory-purple.svg)](docs/ARCHITECTURE.md)
[![Cognee Core](https://img.shields.io/badge/cognee%20core-v1.4.0-blue.svg)](https://docs.cognee.ai)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](docker-compose.yml)

**Ontogram** is a high-performance, containerized hybrid memory system built on the **Cognee 1.4.0 core** to provide persistent, isolated, and shared **Knowledge Graphs** and **Vector Memories** for local AI agents (**Antigravity**, **Pi**, **OpenCode**, and custom scripts).

---

## 🌟 Key Features

* **Zero Core Modifications**: Ontogram is built 100% on top of native out-of-the-box Cognee storage engines (NetworkX/KuzuDB, LanceDB, SQLite) and LiteLLM adapters.
* **Hybrid Multi-Protocol Architecture**:
  * **REST API Daemon (Port 9480)**: Single Cognee core process holding the databases — centralized connection pool preventing database locks across concurrent agents.
  * **Ontogram MCP Bridge (Port 9481, streamable-HTTP)**: Harness/agent-agnostic MCP server exposing `remember`, `recall`, `list_datasets`, and `list_agents` tools. Any MCP client (Claude Code, Antigravity, Pi, OpenCode, Cursor, …) connects at `http://localhost:9481/mcp`. It proxies to the REST daemon, so there is still only one Cognee core process.
  * **Graph Visualizer**: Served by the REST daemon at `http://localhost:9480/api/v1/visualize`. This is the only UI — Ontogram ships **no separate web frontend**; there are exactly two long-lived processes (REST daemon + MCP bridge) and two published ports.
* **Non-Blocking Async Ingestion**: Memory ingestion (`remember`) returns **instantly in < 1 sec** (`run_in_background=True`) while building Knowledge Graphs asynchronously.
* **LiteLLM Unified Adapter**: Connect to custom LiteLLM proxy gateways, OpenAI, Gemini, Anthropic, or local Ollama models.
* **Local Fastembed Integration**: Local vector embeddings (`BAAI/bge-small-en-v1.5`) generated on-device with zero embedding API cost.
* **Scoped Multi-Agent Memory Isolation**: Dataset partitioning by scope triple (`deck_global_memory`, `deck_<project>_memory`, `deck_<project>_<session>_memory`); legacy `<agent_id>_memory` partitions still served.

---

## 📁 Repository Structure

```text
.
├── Dockerfile                  # Production container definition
├── docker-compose.yml          # Single-container orchestration (ports 9480 + 9481)
├── .env.example                # Documented config template — copy to .env
├── .env                        # Runtime environment configuration (secrets; not committed)
├── manage_llm.py               # CLI tool to test & update LiteLLM provider settings
├── start_services.py           # Hybrid service orchestrator script
├── agent_client.py             # Client helper library for local agents
├── mcp_config_example.json     # MCP server configuration template
├── README.md                   # Ontogram documentation index
├── docs/                       # Comprehensive documentation suite
│   ├── ARCHITECTURE.md         # System design & multi-agent memory model
│   ├── SETUP_GUIDE.md          # Step-by-step setup & Docker deployment guide
│   ├── LLM_PROVIDERS.md        # LiteLLM, custom gateway, and embedding config
│   └── AGENT_INTEGRATION.md    # Guide for Antigravity, Pi, OpenCode & Python
└── plans/
    └── cognee_hybrid_service_plan.md  # Original architecture plan
```

---

## 🚀 Quick Start

### 1. Docker Deployment (Recommended)

```bash
# Clone or navigate to directory
cd Ontogram

# Create your config from the template, then set LLM_API_KEY
cp .env.example .env

# Start containerized services
docker compose up -d --build

# View container logs
docker compose logs -f
```

A single container runs both Ontogram processes. The services will be live at:
* **REST API Server**: `http://localhost:9480` (Docs: `http://localhost:9480/docs`)
* **Ontogram MCP Bridge**: `http://localhost:9481/mcp` (streamable-HTTP)
* **Graph Visualizer**: `http://localhost:9480/api/v1/visualize` (an endpoint on the REST daemon, not a separate service)

All memory persists on the named Docker volume `cognee_data`, mounted at
`/root/.cognee` — `docker compose down` and rebuilds are safe; `docker compose
down -v` deletes every stored memory.

### Connect any agent to Ontogram memory

Point your MCP client at the HTTP endpoint — this is the harness-agnostic path:

```json
{
  "mcpServers": {
    "cognee-memory": { "type": "http", "url": "http://localhost:9481/mcp" }
  }
}
```

See [mcp_config_example.json](mcp_config_example.json) for a stdio fallback. Tools exposed:

* `remember(text, scope, project_id, session_id, wait)` — store a fact; scoped per project (and optionally per session)
* `recall(query, scope, project_id, session_id)` — query the scoped knowledge graph
* `list_datasets()` — discover which datasets exist
* `list_agents()` — list memory partitions (deck-style and legacy)

Memory is partitioned by a **scope triple** instead of a flat agent id:

| Scope | Dataset | `X-User-Id` |
| :--- | :--- | :--- |
| `global` | `deck_global_memory` | `global` |
| `project` | `deck_<project-slug>_memory` | `<project-slug>` |
| `session` | `deck_<project-slug>_<session-slug>_memory` | `<project-slug>` |

Omitting `project_id` degrades leniently to the global dataset — agents storing
project memory should pass `project_id` explicitly.

> The MCP server key is still registered as `cognee-memory` in the shipped
> configuration files — that identifier is wired into `.mcp.json` and client
> configs, so Ontogram keeps it for backwards compatibility.

---

### 2. Local Python Environment Setup

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Configure LiteLLM model & key
./manage_llm.py --set-endpoint "https://llm-gateway.apps.askml.ai/v1"
./manage_llm.py --set-model "openai/Qwen/Qwen3.6-35B-A3B-FP8"
./manage_llm.py --set-key "YOUR_API_KEY"

# 3. Test connection
./manage_llm.py --test

# 4. Start the local Ontogram service daemon
./start_services.py
```

---

## 🤖 Using with Local Agents

### Store Memory (`remember`)
```bash
./agent_client.py remember "Antigravity agent prefers modular python design and SQLite caching" --user-id antigravity
```

### Recall Memory (`recall`)
```bash
./agent_client.py recall "What does Antigravity agent prefer?" --user-id antigravity
```

---

## 📚 Documentation Index

For detailed guides, refer to the Ontogram documentation suite in `docs/`:

* 🏛 **[Architecture & Memory Model](docs/ARCHITECTURE.md)**: System design, entity extraction pipelines, and multi-tenant memory partitioning.
* 🛠 **[Setup & Deployment Guide](docs/SETUP_GUIDE.md)**: Local setup, Docker Compose, systemd daemonization, and troubleshooting.
* ⚙️ **[LLM & Embedding Providers](docs/LLM_PROVIDERS.md)**: LiteLLM configuration, custom gateways, local Ollama, and Fastembed setup.
* 🔌 **[Agent Integration Guide](docs/AGENT_INTEGRATION.md)**: Configuring Antigravity (MCP), Pi, OpenCode, and custom Python agents.

---

## 🏷 Naming

**Ontogram** is the name of this project — the hybrid memory service, its MCP
bridge, and its multi-agent memory model. **Cognee** refers to the upstream
open-source engine ([docs.cognee.ai](https://docs.cognee.ai)) that Ontogram uses
unmodified as its core: the ECL pipeline, graph/vector stores, and LiteLLM
adapters. Ontogram is *based on Cognee core* and is not affiliated with the
Cognee project.

---

## 📄 License
Ontogram is open-source software licensed under the MIT License.
