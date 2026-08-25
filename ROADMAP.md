# Ontogram Improvement Roadmap

Tracker for the post-recap improvement phases (2026-08-25).
Decisions locked with owner:

- `forget` scope: **dataset-level only** (zero Cognee core modifications)
- Security posture: **loopback default bind + optional `ONTOGRAM_TOKEN`**
- Commits land per-phase; no push until explicitly requested

---

## Phase 1 — Correctness (doc/code drift & naming)

- [x] 1.1 Sync docs with actual MCP contract (`scope` / `project_id` / `session_id`
      triple in `remember`/`recall`, not legacy `agent_id`)
      - README.md
      - docs/AGENT_INTEGRATION.md
      - docs/SETUP_GUIDE.md (stale `/home/himanshu/builds/cognee` paths → portable)
      - docs/ARCHITECTURE.md (partitioning table)
- [x] 1.2 Unify partition naming
      - `list_agents` becomes deck-aware (`deck_global_memory`,
        `deck_<project>_memory`, `deck_<project>_<session>_memory`) while still
        surfacing legacy `<agent_id>_memory` datasets
      - `agent_client.py` gains scope-style naming parity notes / flags

## Phase 2 — Capability

- [x] 2.1 `remember_status` tool: bridge-side job tracking so agents can confirm
      background cognify succeeded (closes the silent-async-failure gap)
- [x] 2.2 `forget` tool: dataset-level delete via REST passthrough
      (`DELETE /api/v1/datasets/{id}`, name→id resolved from the dataset list) —
      coarse-grained by design; refuses lenient scope fallbacks to protect the
      global dataset. Note: Cognee's REST API also exposes per-data-item
      deletion (`DELETE .../data/{data_id}`) if finer granularity is ever
      wanted without core changes.

## Phase 3 — Ops & UX

- [x] 3.1 Security: default bind `127.0.0.1` for MCP bridge (+ daemon guidance),
      opt-in `ONTOGRAM_TOKEN` bearer auth for LAN exposure
      - bridge: loopback default host + pure-ASGI bearer guard when token set
      - `start_services.py`: `COGNEE_BIND_HOST` (default loopback) for both processes
      - compose: ports published on `127.0.0.1` only; docs updated
- [x] 3.2 docker-compose healthcheck (`curl /docs`, start_period 90s) +
      startup ordering (orchestrator waits up to 60s for daemon readiness
      before launching the MCP bridge)
- [x] 3.3 Harness auto-integration
      - integrations/AGENTS_MEMORY.md — memory protocol block for AGENTS.md /
        CLAUDE.md / .cursorrules
      - integrations/memory_bootstrap.py — session hook script
        (recall-on-start / remember-on-end)
      - README integration section; mcp_config_example.json refreshed

## Status log

| Date | Phase | Commit | Notes |
| :--- | :--- | :--- | :--- |
| 2026-08-25 | — | a41d17e | Baseline: mcp>=2 compat + scoped remember/recall landed |
| 2026-08-25 | — | a88686d | fastmcp>=2 dependency (leftover from mcp>=2 compat) |
| 2026-08-25 | — | 8960503 | Roadmap tracker added; graphify-out ignored |
| 2026-08-25 | 1 | dc78ad3 | Docs synced to scope triple; deck-aware list_agents; agent_client scope flags |
| 2026-08-25 | 2 | 114b28a | remember_status job tracking; dataset-level forget with fallback guards; docs updated |
| 2026-08-25 | 3 | 6f5bff4 | Loopback default + ONTOGRAM_TOKEN guard; healthcheck & startup ordering; harness integration assets |
| 2026-08-25 | T | 8e8c968 | Live e2e on OpenCode Go: fixed container-internal bind, stopped baking .env into image, load_env no longer overrides compose env; SETUP_GUIDE issue 5 added |
| 2026-08-25 | D | 6320331 / 82e1e63 | PERFORMANCE.md (measured scaling + concurrency, six scenarios) and QUICKSTART_AGENTS.md |
| 2026-08-25 | S | (this commit) | Auto scope resolution: ONTOGRAM_PROJECT_ID / ONTOGRAM_SESSION_ID env defaults + loud global-degradation warnings on remember/recall; verified live |

## Live test results (2026-08-25, OpenCode Go / deepseek-v4-flash)

| Test | Result |
| :--- | :--- |
| Daemon + MCP bridge startup ordering (wait-for-daemon) | PASS |
| Host→container reachability with loopback port publishing | PASS (after bind fix) |
| REST `remember` async acceptance (<1s) | PASS (345ms) |
| MCP handshake + `tools/list` (all 6 tools) | PASS |
| MCP sync `remember` (real cognify via LLM) | PASS |
| MCP `recall` (correct answer returned) | PASS |
| MCP async `remember` → `remember_status` indexing→ready | PASS (~10s) |
| MCP `forget` dataset delete + graceful re-run refusal | PASS |
| `list_agents` deck-aware grouping vs real datasets | PASS |

Known limitation: for datasets that already existed before a write,
`remember_status` reports "accepted" without completion confirmation
(Cognee creates the dataset row *before* extraction, so bare existence is not
a completion signal). Use `remember(..., wait=True)` for guaranteed indexing.
