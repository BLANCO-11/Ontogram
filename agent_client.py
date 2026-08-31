#!/usr/bin/env python3
"""
agent_client.py - Unified Client Wrapper for Local Agents (Antigravity, Pi, OpenCode)
Provides fast non-blocking helper functions to store and recall memory with dataset and user-id isolation.

Dataset naming:
  * Legacy (default): <user_id>_memory
  * Scoped (opt-in via --scope/--project-id/--session-id): mirrors the MCP bridge
    omp-deck contract -> deck_global_memory, deck_<project>_memory,
    deck_<project>_<session>_memory
"""

import asyncio
import re
import sys
import argparse
from typing import Optional

from ontogram_backend import create_backend, BackendError

DEFAULT_API_URL = "http://localhost:9480"

def slugify(value: str) -> str:
    """Sanitize an identifier into the deck session-slug charset (mirrors the MCP bridge)."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return cleaned or "unknown"

def resolve_dataset(scope: Optional[str], project_id: Optional[str], session_id: Optional[str], user_id: str) -> tuple[str, str]:
    """Return (datasetName, X-User-Id) for either the scoped or legacy contract."""
    if not scope:
        return f"{user_id}_memory", user_id
    if scope == "session" and project_id and session_id:
        return f"deck_{project_id}_{slugify(session_id)}_memory", project_id
    if scope == "project" and project_id:
        return f"deck_{project_id}_memory", project_id
    return "deck_global_memory", "global"

def remember(text: str, user_id: str = "shared-team", dataset_name: Optional[str] = None, async_bg: bool = True, api_url: str = DEFAULT_API_URL, scope: Optional[str] = None, project_id: Optional[str] = None, session_id: Optional[str] = None) -> bool:
    """Store text/context into Cognee memory for a given agent/user ID."""
    if dataset_name:
        target_dataset, effective_user = dataset_name, user_id
    else:
        target_dataset, effective_user = resolve_dataset(scope, project_id, session_id, user_id)
    print(f"[{effective_user}] Storing memory into dataset '{target_dataset}' (Async Background: {async_bg})...")

    async def run():
        backend = await create_backend(base_url=api_url)
        return await backend.remember(text, target_dataset, effective_user, background=async_bg)

    try:
        result = asyncio.run(run())
    except BackendError as e:
        print(f"❌ [{effective_user}] Connection error: {e}")
        return False
    if result.ok:
        print(f"✓ [{effective_user}] Memory accepted successfully in dataset '{target_dataset}'.")
        return True
    print(f"❌ [{effective_user}] HTTP {result.status_code}: {result.detail}")
    return False

def recall(query: str, user_id: str = "shared-team", dataset_name: Optional[str] = None, api_url: str = DEFAULT_API_URL, scope: Optional[str] = None, project_id: Optional[str] = None, session_id: Optional[str] = None) -> Optional[str]:
    """Recall information/context from Cognee Knowledge Graph."""
    if dataset_name:
        target_dataset, effective_user = dataset_name, user_id
    else:
        target_dataset, effective_user = resolve_dataset(scope, project_id, session_id, user_id)
    print(f"[{effective_user}] Recalling memory from dataset '{target_dataset}' for query: '{query}'...")

    async def run():
        backend = await create_backend(base_url=api_url)
        return await backend.recall(query, target_dataset, effective_user)

    try:
        hits = asyncio.run(run())
    except BackendError as e:
        print(f"❌ [{effective_user}] Connection error: {e}")
        return None
    print(f"✓ [{effective_user}] Recall results retrieved.")
    if not hits:
        return ""
    return "\n\n".join(h.text for h in hits)

def main():
    parser = argparse.ArgumentParser(description="Cognee Agent Client Helper")
    parser.add_argument("action", choices=["remember", "recall"], help="Action to perform")
    parser.add_argument("text", help="Text/data to remember or query string to recall")
    parser.add_argument("--user-id", default="shared-team", help="Agent or tenant ID (legacy naming: <user-id>_memory)")
    parser.add_argument("--dataset", default=None, help="Dataset name (defaults to <user_id>_memory, or the scoped deck name)")
    parser.add_argument("--scope", choices=["global", "project", "session"], default=None, help="Scoped-memory contract (deck_* datasets); overrides legacy user-id naming")
    parser.add_argument("--project-id", default=None, help="Project slug for --scope project/session")
    parser.add_argument("--session-id", default=None, help="Session id for --scope session")
    parser.add_argument("--sync", action="store_true", help="Run cognify synchronously instead of async background")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Cognee REST API base URL")

    args = parser.parse_args()

    if args.action == "remember":
        remember(args.text, user_id=args.user_id, dataset_name=args.dataset, async_bg=not args.sync, api_url=args.api_url,
                 scope=args.scope, project_id=args.project_id, session_id=args.session_id)
    elif args.action == "recall":
        output = recall(args.text, user_id=args.user_id, dataset_name=args.dataset, api_url=args.api_url,
                        scope=args.scope, project_id=args.project_id, session_id=args.session_id)
        if output:
            print(f"\n--- Recall Result [{args.user_id}] ---\n{output}\n---------------------------------")

if __name__ == "__main__":
    main()
