#!/usr/bin/env python3
"""
ensure_memory.py — Discover-or-Create for Ontogram project memory

"Use if available else create one" — checks both the local md file and the
Ontogram knowledge graph for a project, syncs them, and guarantees a dataset
exists afterwards. Idempotent; safe to run at every session start.

Flow for project_id="foundry":
  1. Try local md file (default: <project-root>/ONTGRAM.md, or docs/ONTGRAM.md)
  2. Try Ontogram recall (deck_foundry_memory)
  3. Cases:
     - Both exist → merge: ensure md file contains recalled facts (append missing), no duplicate remember
     - Only Ontogram has data → write/update md file from recall hits
     - Only md file has data → push md file content to Ontogram (remember)
     - Neither → create md file from template + seed Ontogram with project scaffold

Usage:
  # from any agent harness (Claude, Opencode) at session start:
  python integrations/ensure_memory.py --project-id foundry --md-file ONTGRAM.md
  python integrations/ensure_memory.py --project-id foundry --md-file docs/ONTGRAM.md --api-url http://localhost:9480

  # explicit project root (useful when script is called from subdir):
  python integrations/ensure_memory.py --project-id foundry --project-root /path/to/foundry

Exit 0 always (never blocks session start); prints what it did.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

# No extra deps: use requests (available in host and container) for direct REST.
# This keeps ensure_memory runnable from any harness without a venv.
try:
    import requests
except ImportError:
    requests = None  # fallback to urllib

DEFAULT_API_URL = os.getenv("COGNEE_API_URL", "http://localhost:9480")

def _recall(api_url: str, query: str, scope: str, project_id: str | None) -> str | None:
    """Direct REST recall — works without agent_client/httpx."""
    # Resolve dataset like cognee_mcp_server does
    def _slug(s: str) -> str:
        import re
        return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-") or "unknown"
    if scope == "project" and project_id:
        dataset = f"deck_{project_id}_memory"
        user_id = project_id
    elif scope == "session" and project_id:
        dataset = f"deck_{project_id}_memory"  # simplified; session not needed for ensure
        user_id = project_id
    else:
        dataset = "deck_global_memory"
        user_id = "global"
    url = api_url.rstrip("/") + "/api/v1/recall"
    try:
        if requests:
            r = requests.post(url, json={"query": query, "datasets": [dataset]}, headers={"X-User-Id": user_id}, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            if not data:
                return None
            # data is list of hits
            texts = [h.get("text","") for h in data if isinstance(h, dict) and h.get("text")]
            return "\n\n".join(texts) if texts else None
        else:
            import json, urllib.request
            req = urllib.request.Request(url, data=json.dumps({"query": query, "datasets": [dataset]}).encode(), headers={"Content-Type":"application/json","X-User-Id": user_id})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                texts = [h.get("text","") for h in data if isinstance(h, dict) and h.get("text")]
                return "\n\n".join(texts) if texts else None
    except Exception as e:
        print(f"[ensure_memory] recall failed: {e}", file=sys.stderr)
        return None

def _remember(api_url: str, text: str, scope: str, project_id: str | None) -> bool:
    import re
    def _slug(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-") or "unknown"
    if scope == "project" and project_id:
        dataset = f"deck_{project_id}_memory"
        user_id = project_id
    else:
        dataset = "deck_global_memory"
        user_id = "global"
    url = api_url.rstrip("/") + "/api/v1/remember"
    try:
        if requests:
            # cognee expects multipart with file
            r = requests.post(url, files={"data": ("memory.txt", text.encode(), "text/plain")}, data={"datasetName": dataset, "run_in_background": "true"}, headers={"X-User-Id": user_id}, timeout=30)
            return r.status_code in (200,201,202)
        else:
            import urllib.request, mimetypes, uuid
            boundary = uuid.uuid4().hex
            body = b""
            # simplified multipart
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="data"; filename="memory.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode() + text.encode() + b"\r\n"
            body += f"--{boundary}\r\n".encode() + f'Content-Disposition: form-data; name="datasetName"\r\n\r\n{dataset}\r\n'.encode()
            body += f"--{boundary}\r\n".encode() + f'Content-Disposition: form-data; name="run_in_background"\r\n\r\ntrue\r\n'.encode()
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-User-Id": user_id})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status in (200,201,202)
    except Exception as e:
        print(f"[ensure_memory] remember failed: {e}", file=sys.stderr)
        return False

DEFAULT_MD_TEMPLATE = """# Ontogram Memory — {project_id}

> Auto-managed by Ontogram (`integrations/ensure_memory.py`). Do not edit the header.
> This file mirrors `deck_{project_id}_memory` (project scope) and `deck_global_memory` when relevant.
> Agents: `recall` this file via Ontogram at session start; `remember` durable facts as they happen.

## Project facts (scope: project)

<!-- Add one dense fact per bullet. The bootstrap will push these to Ontogram if the graph is empty. -->
- 

## Global facts (scope: global)

- 

## Session notes

- 
"""

def _read_md(md_path: Path) -> str | None:
    if md_path.exists() and md_path.is_file():
        try:
            txt = md_path.read_text(encoding="utf-8")
            return txt if txt.strip() else None
        except Exception:
            return None
    return None

def _write_md(md_path: Path, content: str) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(content.rstrip() + "\n", encoding="utf-8")

def _has_meaningful_content(md_text: str | None) -> bool:
    if not md_text:
        return False
    # ignore template boilerplate with only empty bullets
    lines = [l.strip() for l in md_text.splitlines() if l.strip() and not l.strip().startswith("#") and not l.strip().startswith(">") and not l.strip().startswith("<!--")]
    # count non-empty bullets
    bullets = [l for l in lines if l.startswith("-") and len(l) > 2]
    return len(bullets) > 0

def main() -> None:
    p = argparse.ArgumentParser(description="Ontogram discover-or-create (md file + graph)")
    p.add_argument("--project-id", default="foundry", help="Project slug (dataset deck_<project>_memory)")
    p.add_argument("--md-file", default="ONTGRAM.md", help="Path to local md file relative to --project-root (default: ONTGRAM.md)")
    p.add_argument("--project-root", default=None, help="Project root dir (default: auto-detect from md-file or cwd)")
    p.add_argument("--api-url", default=DEFAULT_API_URL, help="Ontogram REST URL")
    p.add_argument("--scope", choices=["global", "project"], default="project", help="Scope to check (project is deck_<project>_memory)")
    args = p.parse_args()

    # Resolve md path
    if args.project_root:
        root = Path(args.project_root).resolve()
    else:
        # if md-file is absolute, use its parent; else use cwd's project root (foundry or ontogram)
        md_candidate = Path(args.md_file)
        if md_candidate.is_absolute():
            md_path = md_candidate
        else:
            # try to find project root by walking up until ONTGRAM.md or .git or foundry marker
            cwd = Path.cwd().resolve()
            md_path = cwd / args.md_file
            # if cwd is inside foundry, this will be correct; if called from ontogram, caller should pass --project-root
    if not args.project_root:
        # md_path already computed above
        pass
    else:
        md_path = (root / args.md_file).resolve()

    md_text = _read_md(md_path)
    md_has = _has_meaningful_content(md_text)

    # Recall from Ontogram
    try:
        # use project scope for project_id, global for global
        scope = args.scope
        proj = args.project_id if scope == "project" else None
        recalled = _recall(
            args.api_url,
            "Summarize all durable context for this project: decisions, architecture, preferences, open threads",
            scope,
            proj,
        )
    except Exception as e:
        print(f"[ensure_memory] Ontogram recall failed ({e}); treating as no data", file=sys.stderr)
        recalled = None

    has_recall = recalled and "(No relevant memories" not in str(recalled) and "(No stored memory" not in str(recalled) and str(recalled).strip()

    # Cases
    if has_recall and md_has:
        # Both exist — ensure md file mentions recalled facts (simple append if not already present)
        combined = md_text or ""
        if str(recalled).strip() not in combined:
            combined = combined.rstrip() + f"\n\n## Synced from Ontogram ({scope}:{args.project_id})\n\n{recalled}\n"
            _write_md(md_path, combined)
            print(f"[ensure_memory] Both present — merged Ontogram hits into {md_path}")
        else:
            print(f"[ensure_memory] Both present — md file already contains Ontogram data ({md_path})")
        print("--- Ontogram memory ---")
        print(recalled)
        return

    if has_recall and not md_has:
        # Only Ontogram has data — materialize md file
        content = DEFAULT_MD_TEMPLATE.format(project_id=args.project_id)
        # inject recalled facts into project facts section
        content = content.replace("- \n\n## Global", f"- Synced from Ontogram on first run:\n{recalled}\n\n## Global")
        _write_md(md_path, content)
        print(f"[ensure_memory] Created {md_path} from Ontogram {scope}:{args.project_id} (had {len(str(recalled))} chars)")
        print("--- Ontogram memory ---")
        print(recalled)
        return

    if not has_recall and md_has:
        # Only md file has data — push to Ontogram
        # Extract bullets as one remember call (dense)
        ok = _remember(
            args.api_url,
            md_text.strip()[:4000],  # cap single remember payload
            scope,
            proj,
        )
        print(f"[ensure_memory] Pushed {md_path} ({len(md_text)} chars) to Ontogram {scope}:{args.project_id} -> {'ok' if ok else 'failed'}")
        if has_recall is not None:
            print("--- Local md (now in Ontogram) ---")
            print(md_text[:1000])
        return

    # Neither — create md template + seed Ontogram with scaffold
    content = DEFAULT_MD_TEMPLATE.format(project_id=args.project_id)
    # remove existing empty file first to force fresh template (we already have empty template)
    if md_path.exists():
        pass
    _write_md(md_path, content)
    seed = f"Project {args.project_id} initialized. Stack: Foundry parent app (server :4000 + Kestra). Memory file created at {md_path.name}."
    try:
        ok = _remember(
            args.api_url,
            seed,
            scope,
            proj,
        )
        print(f"[ensure_memory] Created {md_path} + seeded Ontogram {scope}:{args.project_id} -> {'ok' if ok else 'failed'}")
    except Exception as e:
        print(f"[ensure_memory] Created {md_path} but Ontogram seed failed: {e}", file=sys.stderr)
    print(f"[ensure_memory] No prior data — initialized {md_path} and Ontogram {scope}:{args.project_id}")
    print("--- Template ---")
    print(content)

if __name__ == "__main__":
    main()
