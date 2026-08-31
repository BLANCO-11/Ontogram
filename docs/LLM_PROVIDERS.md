# Ontogram — LLM & Embedding Providers Guide

Ontogram inherits the Cognee core provider stack, which uses **LiteLLM** as its
adapter — enabling seamless integration with cloud providers, custom
OpenAI-compatible proxies, and local embedding engines.

---

## 1. Custom LiteLLM Proxy Gateways (OpenAI-Compatible)

For custom gateways (e.g. `https://llm-gateway.apps.askml.ai/v1` or local LiteLLM Proxy on port 4000):

### Configuration (`.env`)
```env
LLM_PROVIDER="openai"
LLM_MODEL="openai/Qwen/Qwen3.6-35B-A3B-FP8"
LLM_ENDPOINT="https://llm-gateway.apps.askml.ai/v1"
LLM_API_KEY="sk-your-gateway-key"
```

> [!IMPORTANT]
> Always prefix model names with `openai/` when targeting an OpenAI-compatible base URL endpoint so LiteLLM correctly routes request payloads.

### 1a. opencode-go as LLM provisioner (any inference provider, no LiteLLM proxy)

Ontogram now supports any OpenAI-compatible inference provider direct — no LiteLLM gateway required. For **opencode-go** ($10/mo, `https://opencode.ai/docs/go`, `https://opencode.ai/go`), point Ontogram at Go's base URL. The provisioner is still `openai` — opencode-go is not a separate LiteLLM provider string. Cognee internally still uses the LiteLLM *library*, but any OpenAI-compatible `api_base` works.

**Endpoints** (`https://opencode.ai/docs/go#endpoints`):
* `https://opencode.ai/zen/go/v1/chat/completions` — `deepseek-v4-flash`, `glm-5.x`, `kimi-k3`, `mimo-v2.5` (`@ai-sdk/openai-compatible`)
* `https://opencode.ai/zen/go/v1/responses` — `muse-spark-1.2-contributor`, `grok-4.6`, `gpt-5.6-luna` (`@ai-sdk/openai`) — direct `curl` only; Cognee's LiteLLM chat path uses `/chat/completions`
* `https://opencode.ai/zen/go/v1/messages` — `qwen3.6-plus`, `minimax-m3` (`@ai-sdk/anthropic`)
* Catalog: `https://opencode.ai/zen/go/v1/models` — config id is `opencode-go/<model>`, REST uses bare `deepseek-v4-flash`

```env
# Provisioner: opencode-go — chat-compatible example (verified)
LLM_PROVIDER="openai"
LLM_MODEL="openai/deepseek-v4-flash"
LLM_ENDPOINT="https://opencode.ai/zen/go/v1"  # base only; LiteLLM appends /chat/completions → https://opencode.ai/zen/go/v1/chat/completions
LLM_API_KEY="sk-..."  # OPENCODE_API_KEY from https://opencode.ai/auth (same as Zen, billed to Go)
# For muse-spark direct API: LLM_ENDPOINT="https://opencode.ai/zen/go/v1/responses" + model "muse-spark-1.2-contributor" via curl (not via Cognee chat)
```

Verified (`manage_llm.py` now does direct OpenAI-compatible test first, LiteLLM fallback second):
```bash
docker compose exec cognee_hybrid_service python /app/manage_llm.py --status  # shows opencode-go base
docker compose exec cognee_hybrid_service python /app/manage_llm.py --test    # direct 200, curl also 200; muse-spark chat 500, responses 200
# direct curl checks:
curl -H "Authorization: Bearer $KEY" https://opencode.ai/zen/go/v1/chat/completions -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"ping"}]}'
curl -H "Authorization: Bearer $KEY" https://opencode.ai/zen/go/v1/responses -d '{"model":"muse-spark-1.2-contributor","input":"ping"}'
```

---

## 2. OpenAI / Anthropic / Gemini Cloud Direct

### OpenAI Direct
```env
LLM_PROVIDER="openai"
LLM_MODEL="openai/gpt-4o-mini"
LLM_API_KEY="sk-proj-..."
LLM_ENDPOINT=""
```

### Anthropic Claude Direct
```env
LLM_PROVIDER="anthropic"
LLM_MODEL="anthropic/claude-3-5-sonnet-20241022"
LLM_API_KEY="sk-ant-..."
LLM_ENDPOINT=""
```

---

## 3. Local Ollama Integration

If running local models with **Ollama**:

```env
LLM_PROVIDER="ollama"
LLM_MODEL="ollama/llama3.1"
LLM_ENDPOINT="http://localhost:11434"
LLM_API_KEY=""
```

---

## 4. Vector Embedding Providers

### Fastembed (Local ONNX - Recommended)
Generates high-dimensional vector embeddings locally on CPU/GPU without external API costs or rate limits:

```env
EMBEDDING_PROVIDER="fastembed"
EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
```

### Cloud Embeddings (LiteLLM / OpenAI)
```env
EMBEDDING_PROVIDER="openai"
EMBEDDING_MODEL="text-embedding-3-small"
EMBEDDING_API_KEY="sk-proj-..."
```

---

## 5. Using the `manage_llm.py` Utility

You can inspect, test, and update provider configurations interactively using `./manage_llm.py`:

```bash
# View status
./manage_llm.py --status

# Set model & endpoint
./manage_llm.py --set-endpoint "http://localhost:4000" --set-model "openai/llama-3-70b"

# Set API key
./manage_llm.py --set-key "sk-secret-key"

# Test LiteLLM connection
./manage_llm.py --test
```
