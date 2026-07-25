# ====================================================================
# Cognee Core Agent Memory Service Dockerfile
# Production-ready multi-agent memory engine with LiteLLM & Fastembed
# ====================================================================

FROM python:3.12-slim

# Prevent Python from writing bytecode and set unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install core build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install Python packages
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install Cognee, LiteLLM, Fastembed and dependencies
RUN pip install --no-cache-dir \
    "cognee>=1.4.0" \
    "litellm>=1.40.0" \
    fastembed \
    uvicorn \
    fastapi \
    requests \
    httpx \
    "mcp>=1.2.0" \
    python-dotenv

# Copy application files
COPY .env /app/.env
COPY manage_llm.py /app/manage_llm.py
COPY start_services.py /app/start_services.py
COPY agent_client.py /app/agent_client.py
COPY cognee_mcp_server.py /app/cognee_mcp_server.py
COPY mcp_config_example.json /app/mcp_config_example.json

# Make scripts executable
RUN chmod +x /app/manage_llm.py /app/start_services.py /app/agent_client.py /app/cognee_mcp_server.py

# Expose REST API (9480) & MCP Server (9481)
EXPOSE 9480 9481

# Set persistent data directory
VOLUME ["/root/.cognee"]

# Default entrypoint runs the core service orchestrator
CMD ["python", "start_services.py"]
