# ====================================================================
# Ontogram — hybrid memory service for local AI agents
# Built on the official cognee image (pinned) instead of raw python,
# so the core and its storage layout are maintained upstream.
#
# NOTE: cognee/cognee:main moved storage defaults to /cognee-storage and
# now runs multi-tenant (auth required) by default — both match what
# Ontogram's ACL adapter expects. docker-compose.yml mounts the data
# volume at /cognee-storage with legacy-compatible *_ROOT_DIRECTORY
# overrides so existing volumes keep working.
# ====================================================================

FROM cognee/cognee:main

USER root

# MCP/bridge dependencies not shipped in the base image.
# The base image runs a uv-managed virtualenv at /app/.venv WITHOUT pip —
# bootstrap pip first, then install there (not into the system python).
RUN /app/.venv/bin/python -m ensurepip --upgrade >/dev/null \
    && /app/.venv/bin/python -m pip install --no-cache-dir \
    "mcp>=1.2.0" \
    "fastmcp>=2.0.0" \
    requests \
    python-dotenv

WORKDIR /app

# Application files (.env deliberately NOT baked in — see ROADMAP)
COPY manage_llm.py /app/manage_llm.py
COPY start_services.py /app/start_services.py
COPY agent_client.py /app/agent_client.py
COPY cognee_mcp_server.py /app/cognee_mcp_server.py
COPY ontogram_backend.py /app/ontogram_backend.py
COPY mcp_config_example.json /app/mcp_config_example.json

RUN chmod +x /app/manage_llm.py /app/start_services.py /app/agent_client.py /app/cognee_mcp_server.py

# REST API (9480) & MCP bridge (9481)
EXPOSE 9480 9481

VOLUME ["/cognee-storage"]

# Base image ENTRYPOINT starts its own server on :8000 and ignores CMD —
# replace it so our orchestrator (daemon :9480 + MCP bridge :9481) runs.
ENTRYPOINT []
CMD ["python", "start_services.py"]
