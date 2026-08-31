#!/usr/bin/env python3
"""
memory_bootstrap.py - Session bootstrap hook for local AI agent harnesses

Wire this into your harness's session hooks so memory is used automatically
instead of relying on the model remembering to call the MCP tools:

  # Session start (e.g. opencode/claude-code session-start hook):
  # prints previously remembered context for this project to stdout
  ./memory_bootstrap.py recall --project-id myproject

  # Session end / checkpoint:
  ./memory_bootstrap.py remember "Decided to use SQLite; auth middleware done" \
      --project-id myproject

Scopes mirror the MCP bridge omp-deck contract:
  global  -> deck_global_memory
  project -> deck_<project-slug>_memory      (default)
  session -> deck_<project>_<session-slug>_memory
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_client import DEFAULT_API_URL, recall, remember


def main() -> None:
    parser = argparse.ArgumentParser(description="Ontogram session memory bootstrap")
    parser.add_argument("action", choices=["recall", "remember"])
    parser.add_argument("text", nargs="?", default=None, help="Text to remember (remember action only)")
    parser.add_argument("--scope", choices=["global", "project", "session"], default="project")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    args = parser.parse_args()

    if not args.project_id and args.scope in ("project", "session"):
        print(
            f"⚠️  --project-id missing; {args.scope} memory degrades to the global dataset.",
            file=sys.stderr,
        )

    if args.action == "recall":
        output = recall(
            "Summarize all durable context relevant to continuing work on this "
            "project: decisions, preferences, architecture notes, open threads.",
            user_id=args.project_id or "global",
            api_url=args.api_url,
            scope=args.scope,
            project_id=args.project_id,
            session_id=args.session_id,
        )
        if output and "(No relevant memories" not in str(output) and "None" != str(output):
            print("--- Ontogram memory ---")
            print(output)
        else:
            print("(No stored memory yet for this scope.)")
        return

    if not args.text:
        parser.error("remember requires text")
    ok = remember(
        args.text,
        user_id=args.project_id or "global",
        api_url=args.api_url,
        scope=args.scope,
        project_id=args.project_id,
        session_id=args.session_id,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
