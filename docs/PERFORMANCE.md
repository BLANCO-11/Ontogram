# Ontogram Performance Report — With vs Without Persistent Memory

**Method.** Service-level numbers in §1–§3 are **measured** on the reference
deployment: single Docker container on a developer workstation, Cognee 1.4.0
core, `deepseek-v4-flash` via OpenCode Go (LLM), Fastembed local embeddings.
Scenario tables in §4 compose those measurements; cells marked *(est.)* are
labeled estimates. §6 gives a protocol to reproduce everything on your own
agents.

---

## TL;DR

| Question | Answer (measured) |
| :--- | :--- |
| What does it cost an agent to store a fact? | **~280 ms**, non-blocking |
| What does it cost to recall context? | **8.5 s** for a small scoped dataset (~1 LLM call); grows with dataset size |
| Does the bridge slow things down? | No — **10–15 ms** over raw REST |
| Do concurrent agents interfere? | No — 8 parallel writes, **782 ms effective each**, zero failures |
| When does it pay off? | Any session that would otherwise re-read docs or re-ask the user (~5.4k tokens of re-briefing for this repo alone) |

---

## 1. Measured service primitives

| Operation | n | min | median | max | Notes |
| :--- | --: | ---: | ---: | ---: | :--- |
| `remember` async acceptance (REST) | 10 | 221 ms | **278 ms** | 289 ms | Returns before cognify starts |
| `remember` `wait=true` — full ECL | 3 | 14.9 s | 15.9 s | 28.2 s | One dense sentence; LLM-bound |
| `recall` — graph query + LLM synthesis | 5 | 4.0 s | 7.2 s | 18.0 s | Small dataset |
| `list_datasets` (REST) | 10 | 81 ms | 91 ms | 110 ms | No LLM |
| MCP `remember_status` | 10 | 8 ms | **9 ms** | 11 ms | Bridge-local |
| MCP `list_agents` (proxied) | 10 | 101 ms | 105 ms | 119 ms | ≈ REST + ~14 ms proxy overhead |

## 2. Scaling behavior — why scoping matters (measured)

Recall latency is dominated by how much retrieved context the LLM must
synthesize. Measured recall medians by stored-fact count:

```
 5 facts  █████████░░░░░░░░░░░░░░░░░░░░  8.5 s median
20 facts  ██████████████████░░░░░░░░░░░ 17.1 s median
50 facts  ██████████████████████████████ 62.0 s median   (min 44 s)
```

**Implication:** do not pour everything into one global dump. The scope triple
(`global` / `project` / `session`) exists precisely to keep each searchable
dataset small. A per-project dataset fed by normal development stays in the
fast zone; a session-scoped scratchpad stays tiny by construction.

Also observed: occasional LLM outliers (one 60.6 s recall at 5 facts). Recall
latency inherits your provider's variance.

## 3. Concurrency (measured)

8 agents writing simultaneously via the shared daemon:

- Wall time for all 8 accepts: **6.26 s total → 782 ms effective per agent**
- Statuses: `{200: 8}` — zero lock contention, zero failures

This is the hybrid-daemon design working as intended: one Cognee process owns
the databases, so agents never fight over SQLite/LanceDB file locks.

## 4. Scenarios

### S1 — Morning session start ("what was I doing?")

*The most common win. Agent resumes work on a project after N days.*

| | Without Ontogram | With Ontogram |
| :--- | :--- | :--- |
| Steps | Re-read README/ARCHITECTURE/recent diffs; ask user for status | 1 × `recall("summarize decisions, open threads", scope=project)` |
| Latency | 1–5 min of tool calls *(est.)* | **~8.5 s** (measured, small scoped dataset) |
| Tokens consumed | ~5,409 for this repo's doc suite alone (measured) + diff reading *(est.)* | ~200–800 token recall answer *(est.)* |
| Result quality | Whatever the files happen to encode | Decisions *and their rationale*, even if never committed |

### S2 — Mid-task decision lookup ("why did we choose X?")

| | Without | With |
| :--- | :--- | :--- |
| Flow | Interrupt the user, or re-derive from code archaeology | 1 × `recall` |
| Cost | Human interruption (30 s–∞) or minutes of grep *(est.)* | **~8.5 s**, no human involved |
| Failure mode | Rationale was never written down → re-litigate the decision | Stored at decision time with its "because" clause |

### S3 — Recording a decision while working

| | Without | With |
| :--- | :--- | :--- |
| Flow | Hope someone writes it into docs later | Inline `remember(text, scope=project)` |
| Cost | 0 now, paid later as S1/S2 losses | **~280 ms**, non-blocking; indexing verified later via `remember_status` (9 ms) |
| Agent attention | — | None required beyond the one call |

### S4 — Cross-agent knowledge handoff (opencode → pi)

*opencode fixes a gnarly bug; pi hits the same area next day.*

| | Without | With |
| :--- | :--- | :--- |
| Flow | pi re-diagnoses independently | opencode: `remember("Bug X caused by Y; fix Z", scope=project, project_id="shared")` · pi: 1 × `recall` |
| Cost without | Full duplicate diagnosis (minutes–hours) *(est.)* | One write (**~280 ms**) + one read (**~8.5 s**) |
| Isolation | n/a | Other projects can't see it unless you share the scope — isolation is free |

### S5 — Onboarding a new agent or teammate

| | Without | With |
| :--- | :--- | :--- |
| Flow | Walk through docs + verbal history | 1 × broad `recall` over the project dataset |
| Cost | Hours of pairing *(est.)* | Seconds of recall; quality bounded by what was remembered |
| Caveat | — | Only covers what agents chose to remember — pair with committed docs |

### S6 — Session scratchpad (high-churn state)

| | Without | With |
| :--- | :--- | :--- |
| Flow | Keep re-stating context in every prompt | `scope=session` dataset; wiped guilt-free via `forget` when done |
| Cost without | Prompt bloat grows all session *(est.)* | Tiny dataset ⇒ recall stays in the fast zone (§2) |

## 5. Honest limits

- **Recall is not sub-second.** It is one LLM call: seconds, scaling with
  dataset size (§2). Use it once at session start, not in a hot loop.
- **First session shows no savings** — it pays the small remember tax and
  builds the corpus. Sessions 2+ capture the value.
- **Sync ingestion (`wait=true`) costs 15–28 s** — only for when you must
  guarantee the fact is queryable immediately (e.g., store-then-recall in the
  same scripted flow).
- **Garbage in, garbage out.** Undisciplined remembering pollutes recall
  quality faster than it degrades latency. The memory protocol block
  ([integrations/AGENTS_MEMORY.md](../integrations/AGENTS_MEMORY.md)) exists to
  keep agents selective.
- All LLM-bound numbers inherit your provider's rate limits and variance.

## 6. Reproduce it yourself

1. **Baseline:** run your task suite with no memory tools registered. Record
   wall-clock, tokens, questions asked to the human.
2. **Treatment:** same suite, MCP registered *and* the memory protocol in the
   agent instructions.
3. **Cross-session factor:** repeat in a fresh session the next day — the
   delta concentrates there.
4. Compare prompt size at first tool call and time-to-first-productive-action.

Service-level benches are reproducible from this repo: the measurement scripts
drive plain REST/MCP calls (`POST /api/v1/remember`, `POST /api/v1/recall`,
MCP `tools/call`) against `localhost:9480`/`:9481`.
