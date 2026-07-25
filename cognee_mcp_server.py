#!/usr/bin/env python3
"""
cognee_mcp_server.py - Harness/Agent-Agnostic Memory MCP Server for Cognee

A thin Model Context Protocol server that exposes Cognee memory as portable
`remember` / `recall` tools for ANY MCP client (Claude Code, Antigravity, Pi,
OpenCode, Cursor, etc.).

Design: this server does NOT run Cognee in-process. It proxies to the single
REST daemon (cognee.api.client:app on COGNEE_API_URL). Keeping exactly one
Cognee process is what prevents SQLite/LanceDB/KuzuDB write-lock contention
when several agents talk to memory concurrently -- the core promise of this
service. Per-agent isolation is achieved by dataset partitioning
(``<agent_id>_memory``), matching agent_client.py.

Transports:
  * streamable-http (default) -- any agent points at http://<host>:<port>/mcp
  * sse                       -- legacy SSE clients: http://<host>:<port>/sse
  * stdio                     -- clients that prefer spawning a subprocess

Configuration (env vars):
  COGNEE_API_URL        REST daemon base URL           (default http://localhost:9480)
  COGNEE_MCP_TRANSPORT  http | sse | stdio             (default http)
  COGNEE_MCP_HOST       bind host for http/sse         (default 0.0.0.0)
  COGNEE_MCP_PORT       bind port for http/sse         (default 9481)
  COGNEE_DEFAULT_AGENT  fallback agent/tenant id       (default shared-team)
"""

import os
import sys
import argparse
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
API_URL = os.getenv("COGNEE_API_URL", "http://localhost:9480").rstrip("/")
DEFAULT_AGENT = os.getenv("COGNEE_DEFAULT_AGENT", "shared-team")

# Cognify (graph building) can take a while; recall runs an LLM completion.
REMEMBER_SYNC_TIMEOUT = 300.0   # seconds, only used when wait=True
REMEMBER_ASYNC_TIMEOUT = 30.0   # background ingestion returns fast
RECALL_TIMEOUT = 120.0

mcp = FastMCP(
    "cognee-memory",
    host=os.getenv("COGNEE_MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("COGNEE_MCP_PORT", "9481")),
)


def _dataset_for(agent_id: str) -> str:
    return f"{agent_id}_memory"


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
async def remember(text: str, agent_id: str = DEFAULT_AGENT, wait: bool = False) -> str:
    """Store a piece of text into long-term memory (a Cognee knowledge graph).

    Use this to persist facts, preferences, decisions, or context that should
    survive across sessions and be shared or isolated per agent.

    Args:
        text: The information to remember (a sentence, note, or paragraph).
        agent_id: Memory partition / tenant. Each agent gets an isolated
            dataset named ``<agent_id>_memory``. Use "shared-team" for memory
            shared across all agents. Defaults to the configured default agent.
        wait: If True, block until the knowledge graph is built (slower, up to
            a few minutes). If False (default), ingestion runs in the
            background and this returns immediately.
    """
    if not text or not text.strip():
        return "❌ Nothing to remember: `text` was empty."

    dataset = _dataset_for(agent_id)
    files = {"data": ("memory.txt", text.encode("utf-8"), "text/plain")}
    data = {
        "datasetName": dataset,
        "run_in_background": "false" if wait else "true",
    }
    headers = {"X-User-Id": agent_id}
    timeout = REMEMBER_SYNC_TIMEOUT if wait else REMEMBER_ASYNC_TIMEOUT

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{API_URL}/api/v1/remember",
                files=files,
                data=data,
                headers=headers,
            )
    except httpx.RequestError as exc:
        return f"❌ Could not reach Cognee memory backend at {API_URL}: {exc}"

    if resp.status_code in (200, 201, 202):
        mode = "stored and indexed" if wait else "accepted (indexing in background)"
        return f"✓ Memory {mode} for agent '{agent_id}' (dataset '{dataset}')."
    return f"❌ Memory backend returned HTTP {resp.status_code}: {resp.text[:500]}"


@mcp.tool()
async def recall(query: str, agent_id: str = DEFAULT_AGENT) -> str:
    """Recall relevant information from long-term memory for a natural-language query.

    Searches the agent's Cognee knowledge graph and returns a synthesized answer
    grounded in previously remembered facts.

    Args:
        query: The natural-language question or lookup.
        agent_id: Memory partition / tenant to search (dataset
            ``<agent_id>_memory``). Use "shared-team" for shared memory.
            Defaults to the configured default agent.
    """
    if not query or not query.strip():
        return "❌ Empty query."

    dataset = _dataset_for(agent_id)
    payload = {"query": query, "datasetName": dataset}
    headers = {"X-User-Id": agent_id}

    try:
        async with httpx.AsyncClient(timeout=RECALL_TIMEOUT) as client:
            resp = await client.post(
                f"{API_URL}/api/v1/recall",
                json=payload,
                headers=headers,
            )
    except httpx.RequestError as exc:
        return f"❌ Could not reach Cognee memory backend at {API_URL}: {exc}"

    if resp.status_code != 200:
        return f"❌ Memory backend returned HTTP {resp.status_code}: {resp.text[:500]}"

    try:
        results = resp.json()
    except ValueError:
        return f"❌ Unexpected non-JSON response: {resp.text[:500]}"

    # Response is a list of recall results; surface the readable text.
    texts = []
    for item in results if isinstance(results, list) else []:
        t = (item.get("text") or "").strip() if isinstance(item, dict) else ""
        if t:
            texts.append(t)

    if not texts:
        return f"(No relevant memories found for agent '{agent_id}'.)"
    return "\n\n".join(texts)


@mcp.tool()
async def list_agents() -> str:
    """List the memory partitions (agents/tenants) that currently exist.

    Returns the known ``<agent_id>_memory`` datasets so a client can discover
    which agents have stored memory.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{API_URL}/api/v1/datasets")
    except httpx.RequestError as exc:
        return f"❌ Could not reach Cognee memory backend at {API_URL}: {exc}"

    if resp.status_code != 200:
        return f"❌ Memory backend returned HTTP {resp.status_code}: {resp.text[:500]}"

    try:
        datasets = resp.json()
    except ValueError:
        return f"❌ Unexpected non-JSON response: {resp.text[:500]}"

    names = []
    for d in datasets if isinstance(datasets, list) else []:
        name = d.get("name") if isinstance(d, dict) else None
        if name:
            agent = name[:-7] if name.endswith("_memory") else name
            names.append(f"  • {agent}  (dataset: {name})")

    if not names:
        return "(No memory partitions yet. Use `remember` to create one.)"
    return "Memory partitions:\n" + "\n".join(names)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Cognee agent-agnostic memory MCP server")
    parser.add_argument(
        "--transport",
        choices=["http", "sse", "stdio"],
        default=os.getenv("COGNEE_MCP_TRANSPORT", "http"),
        help="MCP transport (default: http / streamable-http)",
    )
    args = parser.parse_args()

    if args.transport == "http":
        transport = "streamable-http"
        print(
            f"🧠 Cognee Memory MCP (streamable-http) on "
            f"http://{mcp.settings.host}:{mcp.settings.port}/mcp  →  backend {API_URL}",
            file=sys.stderr,
            flush=True,
        )
    elif args.transport == "sse":
        transport = "sse"
        print(
            f"🧠 Cognee Memory MCP (sse) on "
            f"http://{mcp.settings.host}:{mcp.settings.port}/sse  →  backend {API_URL}",
            file=sys.stderr,
            flush=True,
        )
    else:
        transport = "stdio"
        print(f"🧠 Cognee Memory MCP (stdio)  →  backend {API_URL}", file=sys.stderr, flush=True)

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
