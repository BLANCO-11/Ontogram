# Ontogram Improvement Roadmap

Tracker for the post-recap improvement phases (2026-08-25).
Decisions locked with owner:

- `forget` scope: **dataset-level only** (zero Cognee core modifications)
- Security posture: **loopback default bind + optional `ONTOGRAM_TOKEN`**
- Commits land per-phase; no push until explicitly requested

---

## Phase 1 — Correctness (doc/code drift & naming)

- [ ] 1.1 Sync docs with actual MCP contract (`scope` / `project_id` / `session_id`
      triple in `remember`/`recall`, not legacy `agent_id`)
      - README.md
      - docs/AGENT_INTEGRATION.md
      - docs/SETUP_GUIDE.md (stale `/home/himanshu/builds/cognee` paths → portable)
      - docs/ARCHITECTURE.md (partitioning table)
- [ ] 1.2 Unify partition naming
      - `list_agents` becomes deck-aware (`deck_global_memory`,
        `deck_<project>_memory`, `deck_<project>_<session>_memory`) while still
        surfacing legacy `<agent_id>_memory` datasets
      - `agent_client.py` gains scope-style naming parity notes / flags

## Phase 2 — Capability

- [ ] 2.1 `remember_status` tool: bridge-side job tracking so agents can confirm
      background cognify succeeded (closes the silent-async-failure gap)
- [ ] 2.2 `forget` tool: dataset-level delete via REST passthrough
      (`DELETE /api/v1/datasets/{name}`) — coarse-grained by design

## Phase 3 — Ops & UX

- [ ] 3.1 Security: default bind `127.0.0.1` for MCP bridge (+ daemon guidance),
      opt-in `ONTOGRAM_TOKEN` bearer auth for LAN exposure
- [ ] 3.2 docker-compose healthcheck + startup ordering (daemon ready before bridge)
- [ ] 3.3 Harness auto-integration
      - shipped `.mcp.json` template
      - AGENTS.md memory snippet
      - bootstrap hook script (recall-on-start / remember-on-end)

## Status log

| Date | Phase | Commit | Notes |
| :--- | :--- | :--- | :--- |
| 2026-08-25 | — | a41d17e | Baseline: mcp>=2 compat + scoped remember/recall landed |
