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
