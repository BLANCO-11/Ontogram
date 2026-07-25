#!/usr/bin/env python3
"""
agent_client.py - Unified Client Wrapper for Local Agents (Antigravity, Pi, OpenCode)
Provides fast non-blocking helper functions to store and recall memory with dataset and user-id isolation.
"""

import sys
import argparse
import requests
from typing import Optional

DEFAULT_API_URL = "http://localhost:9480"

def remember(text: str, user_id: str = "shared-team", dataset_name: Optional[str] = None, async_bg: bool = True, api_url: str = DEFAULT_API_URL) -> bool:
    """Store text/context into Cognee memory for a given agent/user ID."""
    target_dataset = dataset_name or f"{user_id}_memory"
    print(f"[{user_id}] Storing memory into dataset '{target_dataset}' (Async Background: {async_bg})...")
    url = f"{api_url.rstrip('/')}/api/v1/remember"
    headers = {"X-User-Id": user_id}
    
    files = {
        "data": ("memory.txt", text.encode("utf-8"), "text/plain")
    }
    data = {
        "datasetName": target_dataset,
        "run_in_background": "true" if async_bg else "false"
    }
    
    # Synchronous cognify (graph building) can take minutes; background returns fast.
    timeout = 30 if async_bg else 300
    try:
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
        if resp.status_code in (200, 201, 202):
            print(f"✓ [{user_id}] Memory accepted successfully in dataset '{target_dataset}'.")
            return True
        else:
            print(f"❌ [{user_id}] HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

def recall(query: str, user_id: str = "shared-team", dataset_name: Optional[str] = None, api_url: str = DEFAULT_API_URL) -> Optional[str]:
    """Recall information/context from Cognee Knowledge Graph."""
    target_dataset = dataset_name or f"{user_id}_memory"
    print(f"[{user_id}] Recalling memory from dataset '{target_dataset}' for query: '{query}'...")
    url = f"{api_url.rstrip('/')}/api/v1/recall"
    headers = {"X-User-Id": user_id}
    payload = {
        "query": query,
        "datasetName": target_dataset
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✓ [{user_id}] Recall results retrieved.")
            return str(result)
        else:
            print(f"❌ [{user_id}] HTTP {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Cognee Agent Client Helper")
    parser.add_argument("action", choices=["remember", "recall"], help="Action to perform")
    parser.add_argument("text", help="Text/data to remember or query string to recall")
    parser.add_argument("--user-id", default="shared-team", help="Agent or tenant ID (e.g. antigravity, pi, opencode, shared-team)")
    parser.add_argument("--dataset", default=None, help="Dataset name (defaults to <user_id>_memory)")
    parser.add_argument("--sync", action="store_true", help="Run cognify synchronously instead of async background")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Cognee REST API base URL")
    
    args = parser.parse_args()
    
    if args.action == "remember":
        remember(args.text, user_id=args.user_id, dataset_name=args.dataset, async_bg=not args.sync, api_url=args.api_url)
    elif args.action == "recall":
        output = recall(args.text, user_id=args.user_id, dataset_name=args.dataset, api_url=args.api_url)
        if output:
            print(f"\n--- Recall Result [{args.user_id}] ---\n{output}\n---------------------------------")

if __name__ == "__main__":
    main()
