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
service. Isolation is achieved by dataset partitioning.

Scoped-memory contract (shared with the omp-deck MemoryService): memory is
partitioned into ``deck_global_memory``, ``deck_<project-slug>_memory`` and
``deck_<project-slug>_<session-slug>_memory`` datasets; the ``X-User-Id``
header is ``global`` or the project slug. ``remember``/``recall`` resolve a
(scope, project_id, session_id) triple into that naming before proxying, so
agents and the deck agree on where a fact lands. Legacy ``<agent_id>_memory``
partitioning is still served by ``list_agents`` but new writes use the deck
naming above.

Transports:
  * streamable-http (default) -- any agent points at http://<host>:<port>/mcp
  * sse                       -- legacy SSE clients: http://<host>:<port>/sse
  * stdio                     -- clients that prefer spawning a subprocess

Configuration (env vars):
  COGNEE_API_URL        REST daemon base URL           (default http://localhost:9480)
  COGNEE_MCP_TRANSPORT  http | sse | stdio             (default http)
  COGNEE_MCP_HOST       bind host for http/sse         (default 127.0.0.1 — loopback;
                        set 0.0.0.0 deliberately to expose beyond localhost)
  COGNEE_MCP_PORT       bind port for http/sse         (default 9481)
  ONTOGRAM_TOKEN        optional bearer token. When set, every HTTP request to
                        this bridge must carry `Authorization: Bearer <token>`;
                        requests without it get 401. Recommended whenever the
                        bridge binds beyond loopback.
"""

import os
import re
import sys
import argparse
import asyncio
import time
import uuid
from typing import Literal, Optional

import httpx

try:
    # mcp < 2: FastMCP ships inside the mcp package (constructor takes host/port).
    from mcp.server.fastmcp import FastMCP

    _FASTMCP_FLAVOR = "mcp"
except ImportError:
    # mcp >= 2: FastMCP moved to the standalone `fastmcp` package. The API is
    # the same except the constructor dropped host/port — they move to run().
    from fastmcp import FastMCP

    _FASTMCP_FLAVOR = "fastmcp"

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
API_URL = os.getenv("COGNEE_API_URL", "http://localhost:9480").rstrip("/")
MCP_HOST = os.getenv("COGNEE_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("COGNEE_MCP_PORT", "9481"))
ONTOGRAM_TOKEN = os.getenv("ONTOGRAM_TOKEN", "").strip()

# Cognify (graph building) can take a while; recall runs an LLM completion.
REMEMBER_SYNC_TIMEOUT = 300.0   # seconds, only used when wait=True
REMEMBER_ASYNC_TIMEOUT = 30.0   # background ingestion returns fast
RECALL_TIMEOUT = 120.0

# --------------------------------------------------------------------------- #
# Job tracking (bridge-side, closes the async ingestion loop)
# --------------------------------------------------------------------------- #
# The daemon accepts `remember` instantly and cognifies in the background;
# without tracking, an agent never learns whether indexing actually finished.
# The bridge keeps a small in-memory ledger per dataset and polls the daemon's
# dataset list until a newly-created dataset shows up. Limitation (by design,
# no Cognee core modifications): for datasets that already existed we cannot
# observe the transition, so those jobs are reported as accepted-but-untracked
# — pass wait=True when guaranteed indexing matters.

JOB_POLL_INTERVAL = 5.0     # seconds between dataset-list probes
JOB_POLL_TIMEOUT = 600.0    # give up tracking after 10 minutes
JOBS_KEEP_PER_DATASET = 20

_JOBS: dict[str, list[dict]] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _record_job(dataset: str, state: str, detail: str = "") -> dict:
    entry = {
        "job_id": uuid.uuid4().hex[:8],
        "submitted": _now(),
        "state": state,
        "detail": detail,
    }
    history = _JOBS.setdefault(dataset, [])
    history.append(entry)
    del history[:-JOBS_KEEP_PER_DATASET]
    return entry


def _update_job(dataset: str, job_id: str, state: str, detail: str = "") -> None:
    for entry in reversed(_JOBS.get(dataset, [])):
        if entry["job_id"] == job_id:
            entry["state"] = state
            entry["detail"] = detail
            entry["updated"] = _now()
            return


async def _fetch_dataset_names() -> Optional[set[str]]:
    """Return the set of dataset names known to the daemon, or None if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{API_URL}/api/v1/datasets")
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    try:
        datasets = resp.json()
    except ValueError:
        return None
    return {d.get("name") for d in datasets if isinstance(d, dict) and d.get("name")}


async def _track_ingestion(dataset: str, job_id: str, existed_before: bool) -> None:
    if existed_before:
        # Dataset already visible before this write; its appearance cannot be
        # used as a completion signal without touching Cognee core. Be honest.
        _update_job(dataset, job_id, "accepted",
                    "dataset already existed; async completion not observable "
                    "(use remember(..., wait=True) for guaranteed indexing)")
        return

    deadline = time.monotonic() + JOB_POLL_TIMEOUT
    while time.monotonic() < deadline:
        await asyncio.sleep(JOB_POLL_INTERVAL)
        names = await _fetch_dataset_names()
        if names is None:
            # Transient backend hiccup vs real failure: keep polling until timeout.
            continue
        if dataset in names:
            _update_job(dataset, job_id, "ready", "knowledge graph built and dataset indexed")
            return

    _update_job(dataset, job_id, "timeout",
                f"dataset '{dataset}' did not appear within {int(JOB_POLL_TIMEOUT)}s")

if _FASTMCP_FLAVOR == "mcp":
    mcp = FastMCP("cognee-memory", host=MCP_HOST, port=MCP_PORT)
else:
    mcp = FastMCP("cognee-memory")


def _slugify(value: str) -> str:
    """Sanitize an identifier into the deck session-slug charset.

    Non-alphanumerics collapse to a single ``-`` (matches the deck's
    ``datasetNameFor`` contract so both sides derive identical dataset names
    from the same session id).
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return cleaned or "unknown"


def _resolve_dataset(
    scope: str,
    project_id: str | None,
    session_id: str | None,
) -> tuple[str, str]:
    """Resolve (datasetName, X-User-Id) per the omp-deck scoped-memory contract.

    Contract (mirrored by apps/server/src/memory/service.ts `datasetNameFor`):
      * global  -> ``deck_global_memory``, X-User-Id ``global``
      * project -> ``deck_<project-slug>_memory``, X-User-Id ``<project-slug>``
      * session -> ``deck_<project-slug>_<session-slug>_memory``,
                   X-User-Id ``<project-slug>``

    Missing ids degrade leniently: a session scope without ids falls back to
    project (then global), and a project scope without a project id lands in
    the global dataset. Callers that want project/session memory MUST pass
    project_id explicitly.
    """
    if scope == "session" and project_id and session_id:
        return f"deck_{project_id}_{_slugify(session_id)}_memory", project_id
    if scope == "project" and project_id:
        return f"deck_{project_id}_memory", project_id
    return "deck_global_memory", "global"


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
async def remember(
    text: str,
    scope: Literal["global", "project", "session"] = "project",
    project_id: str | None = None,
    session_id: str | None = None,
    wait: bool = False,
) -> str:
    """Store a piece of text into long-term memory (a Cognee knowledge graph).

    Use this to persist facts, preferences, decisions, or context that should
    survive across sessions and be scoped per project (and optionally per
    session). Dataset + X-User-Id are derived from the scope triple per the
    omp-deck contract: ``deck_global_memory``, ``deck_<project-slug>_memory``,
    ``deck_<project-slug>_<session-slug>_memory``.

    Args:
        text: The information to remember (a sentence, note, or paragraph).
        scope: Memory partition scope: "global" (shared across all projects),
            "project" (one dataset per project slug), or "session" (a
            per-session dataset inside a project). Defaults to "project"; when
            project_id is absent the memory degrades to the global dataset —
            agents storing project memory MUST pass project_id explicitly.
        project_id: Project slug owning this memory. Required for scope
            "project"; also required together with session_id for scope
            "session".
        session_id: Deck session id; sanitized into a session slug for the
            dataset name. Only used with scope "session".
        wait: If True, block until the knowledge graph is built (slower, up to
            a few minutes). If False (default), ingestion runs in the
            background and this returns immediately.
    """
    if not text or not text.strip():
        return "❌ Nothing to remember: `text` was empty."

    dataset, user_id = _resolve_dataset(scope, project_id, session_id)

    existed_before = dataset in (await _fetch_dataset_names() or set())

    files = {"data": ("memory.txt", text.encode("utf-8"), "text/plain")}
    data = {
        "datasetName": dataset,
        "run_in_background": "false" if wait else "true",
    }
    headers = {"X-User-Id": user_id}
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
        if wait:
            _record_job(dataset, "ready", "synchronous ingestion completed")
            mode = "stored and indexed"
        else:
            entry = _record_job(dataset, "indexing", "accepted by daemon; cognify running in background")
            asyncio.create_task(_track_ingestion(dataset, entry["job_id"], existed_before))
            mode = f"accepted (indexing in background; job {entry['job_id']} — check with remember_status)"
        return f"✓ Memory {mode} for scope '{scope}' (dataset '{dataset}')."
    return f"❌ Memory backend returned HTTP {resp.status_code}: {resp.text[:500]}"


@mcp.tool()
async def recall(
    query: str,
    scope: Literal["global", "project", "session"] = "project",
    project_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Recall relevant information from long-term memory for a natural-language query.

    Searches the scoped Cognee knowledge graph and returns a synthesized answer
    grounded in previously remembered facts. The scope triple resolves to the
    same dataset naming as ``remember`` (omp-deck contract) — pass the same
    scope/project_id/session_id you used when storing.

    Args:
        query: The natural-language question or lookup.
        scope: Memory partition scope: "global", "project", or "session".
            Defaults to "project"; without project_id the recall degrades to
            the global dataset.
        project_id: Project slug whose memory should be searched. Required for
            scope "project"; also required together with session_id for scope
            "session".
        session_id: Deck session id (sanitized into a session slug for the
            dataset name). Only used with scope "session".
    """
    if not query or not query.strip():
        return "❌ Empty query."

    dataset, user_id = _resolve_dataset(scope, project_id, session_id)
    payload = {"query": query, "datasetName": dataset}
    headers = {"X-User-Id": user_id}

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
        return f"(No relevant memories found for scope '{scope}' dataset '{dataset}'.)"
    return "\n\n".join(texts)


@mcp.tool()
async def remember_status(
    scope: Literal["global", "project", "session"] = "project",
    project_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Check whether background `remember` ingestions finished building their knowledge graphs.

    Reports the recent ingestion jobs tracked by this bridge, newest first, with
    one of these states: "indexing" (still building), "ready" (graph built and
    dataset indexed), "accepted" (dataset already existed — completion not
    observable; use wait=True for guarantees), or "timeout" (dataset never appeared).

    Args:
        scope: Scope triple of the dataset to inspect. Omitted datasets show all.
        project_id: Project slug whose memory jobs should be shown.
        session_id: Session id for scope "session".
    """
    if not _JOBS:
        return "(No ingestion jobs tracked since bridge start.)"

    dataset, _ = _resolve_dataset(scope, project_id, session_id)
    targets = [dataset] if dataset in _JOBS else sorted(_JOBS)

    lines = []
    for name in targets:
        for entry in reversed(_JOBS[name]):
            line = f"  • [{entry['state']}] {name} job {entry['job_id']} submitted {entry['submitted']}"
            if entry.get("detail"):
                line += f" — {entry['detail']}"
            lines.append(line)

    if not lines:
        return f"(No jobs tracked for dataset '{dataset}'.)"
    return "Recent ingestion jobs:\n" + "\n".join(lines)


@mcp.tool()
async def forget(
    scope: Literal["global", "project", "session"] = "project",
    project_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Delete an entire memory partition (dataset) and everything remembered in it.

    Coarse-grained by design: the whole scoped dataset is removed — global,
    per-project, or per-session. There is no fact-level deletion; to start over
    for one project, forget its project-scoped dataset and re-remember what
    should be kept (or store it under a new project slug).

    Args:
        scope: Which partition to delete: "global", "project" (requires
            project_id), or "session" (requires project_id and session_id).
        project_id: Project slug owning the memory to delete.
        session_id: Session id for scope "session".
    """
    if scope == "global":
        pass  # explicit global deletion is allowed
    elif scope == "session" and not (project_id and session_id):
        return ("❌ Refusing to degrade: session scope needs both project_id and "
                "session_id. A wrong fallback here would delete the wrong dataset.")
    elif scope == "project" and not project_id:
        return ("❌ Refusing to degrade: project scope needs project_id. A wrong "
                "fallback here would delete the global dataset.")

    dataset, user_id = _resolve_dataset(scope, project_id, session_id)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            listing = await client.get(f"{API_URL}/api/v1/datasets")
            if listing.status_code != 200:
                return f"❌ Memory backend returned HTTP {listing.status_code}: {listing.text[:500]}"
            try:
                datasets = listing.json()
            except ValueError:
                return f"❌ Unexpected non-JSON response: {listing.text[:500]}"

            target = next(
                (d for d in datasets if isinstance(d, dict) and d.get("name") == dataset),
                None,
            )
            if target is None or "id" not in target:
                return f"(Nothing to forget: no dataset named '{dataset}' exists.)"

            resp = await client.delete(f"{API_URL}/api/v1/datasets/{target['id']}")
    except httpx.RequestError as exc:
        return f"❌ Could not reach Cognee memory backend at {API_URL}: {exc}"

    if resp.status_code in (200, 202, 204):
        return f"✓ Forgot dataset '{dataset}' ({scope} scope). All memories in it are gone."
    return f"❌ Memory backend returned HTTP {resp.status_code}: {resp.text[:500]}"


@mcp.tool()
async def list_datasets() -> str:
    """List every dataset known to the Cognee memory backend.

    Passthrough of ``GET {COGNEE_API_URL}/api/v1/datasets``. Use this to
    discover which scoped datasets (``deck_global_memory``,
    ``deck_<project-slug>_memory``, ``deck_<project-slug>_<session-slug>_memory``)
    currently exist before recalling.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{API_URL}/api/v1/datasets")
    except httpx.RequestError as exc:
        return f"❌ Could not reach Cognee memory backend at {API_URL}: {exc}"

    if resp.status_code != 200:
        return f"❌ Memory backend returned HTTP {resp.status_code}: {resp.text[:500]}"
    return resp.text


@mcp.tool()
async def list_agents() -> str:
    """List the memory partitions that currently exist.

    Groups datasets by the scoped-memory contract: the global dataset, per-project
    datasets (``deck_<project-slug>_memory``), per-session datasets
    (``deck_<project-slug>_<session-slug>_memory``), plus any legacy
    ``<agent_id>_memory`` partitions from before scoping was introduced.
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

    global_ds: list[str] = []
    projects: dict[str, list[str]] = {}
    legacy: list[str] = []

    for d in datasets if isinstance(datasets, list) else []:
        name = d.get("name") if isinstance(d, dict) else None
        if not name:
            continue
        if name == "deck_global_memory":
            global_ds.append(name)
        elif name.startswith("deck_") and name.endswith("_memory"):
            parts = name[len("deck_"): -len("_memory")].split("_", 1)
            project = parts[0] if parts else "?"
            projects.setdefault(project, []).append(name)
        elif name.endswith("_memory"):
            legacy.append(name)
        else:
            legacy.append(name)

    sections = []
    if global_ds:
        sections.append("Global:\n  • deck_global_memory")
    if projects:
        lines = []
        for project in sorted(projects):
            scoped = sorted(projects[project])
            proj_ds = [n for n in scoped if n == f"deck_{project}_memory"]
            sess_ds = [n for n in scoped if n != f"deck_{project}_memory"]
            entry = f"  • project '{project}'"
            if proj_ds:
                entry += f"\n      dataset: {proj_ds[0]}"
            for s in sess_ds:
                entry += f"\n      session dataset: {s}"
            lines.append(entry)
        sections.append("Scoped (deck contract):\n" + "\n".join(lines))
    if legacy:
        lines = [f"  • {n[:-7] if n.endswith('_memory') else n}  (dataset: {n})" for n in sorted(legacy)]
        sections.append("Legacy agent partitions:\n" + "\n".join(lines))

    if not sections:
        return "(No memory partitions yet. Use `remember` to create one.)"
    return "Memory partitions:\n" + "\n".join(sections)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def _bearer_guard(app):
    """Pure-ASGI middleware enforcing `Authorization: Bearer <ONTOGRAM_TOKEN>`."""
    expected = f"Bearer {ONTOGRAM_TOKEN}".encode()

    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            if headers.get(b"authorization") != expected:
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({"type": "http.response.body", "body": b"Unauthorized: missing or invalid bearer token"})
                return
        await app(scope, receive, send)

    return wrapped


def _streamable_http_asgi_app():
    """Best-effort ASGI app across mcp<2 (mcp.server.fastmcp) and mcp>=2 (fastmcp)."""
    if hasattr(mcp, "streamable_http_app"):
        return mcp.streamable_http_app()
    return mcp.http_app(path="/mcp")


def _run_http(transport: str) -> None:
    url_path = "/mcp" if transport == "streamable-http" else "/sse"
    print(
        f"🧠 Cognee Memory MCP ({transport}) on "
        f"http://{MCP_HOST}:{MCP_PORT}{url_path}  →  backend {API_URL}"
        + ("  [bearer token required]" if ONTOGRAM_TOKEN else ""),
        file=sys.stderr,
        flush=True,
    )
    if ONTOGRAM_TOKEN:
        import uvicorn

        uvicorn.run(_bearer_guard(_streamable_http_asgi_app()), host=MCP_HOST, port=MCP_PORT)
    elif _FASTMCP_FLAVOR == "fastmcp":
        mcp.run(transport=transport, host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run(transport=transport)


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
        _run_http("streamable-http")
    elif args.transport == "sse":
        _run_http("sse")
    else:
        transport = "stdio"
        print(f"🧠 Cognee Memory MCP (stdio)  →  backend {API_URL}", file=sys.stderr, flush=True)
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()
