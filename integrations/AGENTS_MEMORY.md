# Ontogram Memory Protocol (for AGENTS.md / CLAUDE.md / .cursorrules)

Paste this block into your harness's agent instructions file so the agent
actually *uses* Ontogram memory instead of ignoring it. Adjust tool names to
your harness's MCP namespace (`mcp__cognee-memory__*` in Claude Code, etc.).

---

## Long-term memory (Ontogram MCP at http://localhost:9481/mcp)

You have persistent memory tools backed by a knowledge graph. Use them
proactively:

**At session start** — before doing project work, recall existing context:

    recall(query="project decisions, architecture, preferences, open threads",
           scope="project", project_id="<current-project-slug>")

**When something durable happens**, remember it immediately (do not wait to be
asked):

- A decision is made and its rationale ("chose X over Y because Z")
- An architectural constraint or preference is stated
- A non-obvious bug cause or fix worth remembering
- The user states a workflow or communication preference

    remember(text="<one dense sentence>", scope="project",
             project_id="<current-project-slug>")

**Scope rules:**

| Scope | When to use |
| :--- | :--- |
| `global` | User-level facts true across all projects |
| `project` | Default for anything about this codebase (always pass `project_id`) |
| `session` | Scratch state only relevant within one session |

**Before finishing a session** with significant outcomes, store a summary:

    remember(text="Session summary: <what changed and why>",
             scope="project", project_id="<current-project-slug>")

**Hygiene:** memory compounds — prefer one dense fact per `remember` call over
transcripts. Do not store secrets, tokens, or credentials.

## Discover-or-Create (use if available else create)

At session start, ensure the project's memory exists locally *and* in Ontogram — idempotent, works from any harness without MCP:

    python integrations/ensure_memory.py --project-id <current-project-slug> --md-file ONTGRAM.md

This checks `ONTGRAM.md` (or `docs/ONTGRAM.md`) and `deck_<project>_memory` in Ontogram:
- both exist → merges recall hits into md
- only Ontogram → writes md from graph
- only md → pushes md to graph
- neither → creates md template + seeds graph

See `docs/CONNECT.md#4` and `integrations/ensure_memory.py:1` for full flow. Foundry example: `foundry/ONTGRAM.md` ↔ `deck_foundry_memory`.

## Terminal fallback (no MCP support)

    ./integrations/memory_bootstrap.py recall --project-id myproject
    ./integrations/memory_bootstrap.py remember "..." --project-id myproject
