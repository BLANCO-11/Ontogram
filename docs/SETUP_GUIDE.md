# Ontogram — Setup & Deployment Guide

This guide covers local environment setup, Docker Compose deployment, environment
variable configuration, and troubleshooting for **Ontogram** (based on Cognee core).

---

## 1. Prerequisites

* **Operating System**: Linux / macOS / Windows (WSL2)
* **Python**: Python 3.10+ (Python 3.12 recommended)
* **Docker & Docker Compose** (Optional, for containerized execution)

---

## 2. Option A: Docker Deployment (Recommended)

### Building and Running Ontogram Services
```bash
cd Ontogram

# Create your runtime config from the documented template
cp .env.example .env
# ...then edit .env and set LLM_API_KEY (plus model/endpoint if not using the default gateway)

# Build Docker image and start container detached
docker compose up -d --build

# View real-time container logs
docker compose logs -f

# Check container status
docker compose ps
```

This brings up a **single container** (`cognee_hybrid_service`) running both
Ontogram processes and publishing two ports **on loopback only** (memory stays
on this machine; edit the compose port mappings and set `ONTOGRAM_TOKEN` to
expose deliberately):

| URL | What it is |
| :--- | :--- |
| `http://localhost:9480` | REST API daemon |
| `http://localhost:9480/docs` | Swagger / OpenAPI docs |
| `http://localhost:9480/api/v1/visualize` | Knowledge graph visualizer |
| `http://localhost:9481/mcp` | Ontogram MCP bridge (streamable-HTTP) |

There is no separate web dashboard container or frontend port — the visualizer
is an endpoint on the daemon.

### Stopping Services
```bash
docker compose down          # stops the container, KEEPS all memory
docker compose down -v       # also DELETES the cognee_data volume (all memory)
```

> [!WARNING]
> Memory lives on the named volume `cognee_data` (mounted at `/root/.cognee`).
> Rebuilds and `docker compose down` are safe; `-v` is irreversible.

---

## 3. Option B: Local Virtual Environment Setup

### Installation Steps
```bash
# 1. Navigate to directory
cd Ontogram

# 2. Activate Python virtual environment
source .venv/bin/activate

# 2a. Create your config from the template (skip if .env already exists)
cp .env.example .env

# 3. Configure LLM Provider & Gateway URL
./manage_llm.py --set-endpoint "https://llm-gateway.apps.askml.ai/v1"
./manage_llm.py --set-model "openai/Qwen/Qwen3.6-35B-A3B-FP8"
./manage_llm.py --set-key "YOUR_API_KEY_HERE"

# 4. Test provider connectivity
./manage_llm.py --test

# 5. Launch the Ontogram background daemon service
./start_services.py
```

---

## 4. Environment Variables (`.env`) Reference

Start from [`.env.example`](../.env.example) — it is the annotated template for
everything below:

```bash
cp .env.example .env
```

Keep `.env` out of version control; it holds your `LLM_API_KEY`. `.env.example`
is the file that gets committed and shared.

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `openai` | LLM provider type (`openai`, `litellm`, `anthropic`, `ollama`) |
| `LLM_MODEL` | `openai/model-name` | Model identifier string (use `openai/` prefix for custom gateways) |
| `LLM_ENDPOINT` | `http://...` | Custom LiteLLM proxy base URL |
| `LLM_API_KEY` | `sk-...` | API authorization key |
| `EMBEDDING_PROVIDER` | `fastembed` | Embedding engine (`fastembed` for local, `litellm` for cloud) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model identifier |
| `COGNEE_BACKEND_PORT` | `9480` | FastAPI Backend REST API port |
| `COGNEE_MCP_PORT` | `9481` | Ontogram MCP bridge port |
| `COGNEE_MCP_TRANSPORT` | `http` | MCP transport (`http`, `sse`, `stdio`) |
| `COGNEE_API_URL` | `http://localhost:9480` | REST daemon base URL used by the MCP bridge |
| `COGNEE_SKIP_CONNECTION_TEST` | `true` | Skip startup connection timeout check |
| `COGNEE_BIND_HOST` | `127.0.0.1` | Bind host for both processes (local mode). Set `0.0.0.0` deliberately to serve beyond localhost. |
| `ONTOGRAM_TOKEN` | *(unset)* | Optional bearer token. When set, the MCP bridge rejects requests without `Authorization: Bearer <token>`. Strongly recommended whenever ports are exposed beyond loopback. |
| `DATA_ROOT_DIRECTORY` | `/root/.cognee/data_storage` | Ingested data location — **must** sit on the volume |
| `SYSTEM_ROOT_DIRECTORY` | `/root/.cognee/cognee_system` | Graph/vector/relational DB location — **must** sit on the volume |
| `CACHE_ROOT_DIRECTORY` | `/root/.cognee/cache` | Cache location — **must** sit on the volume |

> [!IMPORTANT]
> The three `*_ROOT_DIRECTORY` variables are not optional. Cognee core defaults
> to paths inside its own installed package directory, which in Docker lives in
> the image layer — leave them unset and `docker compose up --build` wipes all
> stored memory on every rebuild.

> Environment variables keep their `COGNEE_*` prefix: they are consumed by the
> Cognee core and by Ontogram's own scripts, so renaming them would break
> existing `.env` files and container configs.

> [!NOTE]
> `COGNEE_FRONTEND_PORT` may still be present in your `.env`. It is a leftover
> from the removed web dashboard and is read by nothing — safe to delete.

### Security model

By default everything binds to loopback (`COGNEE_BIND_HOST=127.0.0.1`) and
Docker publishes ports on `127.0.0.1` only, so your memory is reachable solely
from this machine. To serve other machines on your LAN:

1. Set `ONTOGRAM_TOKEN=<random-secret>` in `.env` — the MCP bridge then
   requires an `Authorization: Bearer <token>` header on every request.
2. Change the compose port mappings to `"9480:9480"` / `"9481:9481"` (or set
   `COGNEE_BIND_HOST=0.0.0.0` when running without Docker).

Note the REST daemon itself is stock Cognee and has no token support; only the
MCP bridge enforces `ONTOGRAM_TOKEN`, so prefer agent traffic over MCP when
exposed.

---

## 5. Troubleshooting Common Issues

### Issue 1: LiteLLM `LLM Provider NOT provided`
- **Cause**: Custom LiteLLM gateway models lack the provider prefix.
- **Fix**: Format `LLM_MODEL` as `openai/<your-model-name>` in `.env`.

### Issue 2: `Connection refused on localhost:9480`
- **Cause**: Backend server is not running or crashed on startup.
- **Fix**: Run `./start_services.py` or inspect logs with `docker compose logs -f`.

### Issue 3: Fastembed Missing Module Error
- **Fix**: Install fastembed into your virtual environment: `.venv/bin/python -m pip install fastembed`.

### Issue 4: All memory disappears after a rebuild
- **Cause**: The `*_ROOT_DIRECTORY` variables are unset or point outside the
  volume, so Cognee core wrote its databases into the image layer.
- **Fix**: Confirm `DATA_ROOT_DIRECTORY`, `SYSTEM_ROOT_DIRECTORY`, and
  `CACHE_ROOT_DIRECTORY` all resolve under `/root/.cognee` (see
  `docker-compose.yml`), then verify the volume is populated:
  `docker compose exec cognee_hybrid_service ls -la /root/.cognee`.

### Issue 5: Changed `.env` but the container still uses old values
- **Cause**: `docker compose up -d` does not recreate a running container when
  only the *contents* of `.env` change (e.g. a new `LLM_API_KEY`).
- **Fix**: `docker compose up -d --force-recreate`. Verify with:
  `docker compose exec cognee_hybrid_service printenv LLM_API_KEY`.

### Issue 6: Looking for the web dashboard / a frontend port
- **Cause**: The Next.js dashboard from the original design was removed.
- **Fix**: Nothing to start. Use `http://localhost:9480/api/v1/visualize` for the
  knowledge graph and `http://localhost:9480/docs` for the API. Any lingering
  `COGNEE_FRONTEND_PORT` entry in `.env` is inert.
