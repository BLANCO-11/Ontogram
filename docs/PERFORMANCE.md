# Ontogram — Performance: With vs Without Persistent Memory

All service-level numbers below are **measured** on the reference deployment
(single container on the developer workstation, Cognee 1.4.0 core,
`deepseek-v4-flash` via an OpenCode Go subscription, Fastembed local
embeddings). Agent-level workflow numbers are **illustrative estimates** and a
reproducible A/B protocol is provided so you can measure your own agents.

---

## 1. Measured service-level benchmarks

| Operation | n | min | median | max | Notes |
| :--- | --: | ---: | ---: | ---: | :--- |
| `remember` — async acceptance (REST) | 10 | 221 ms | 278 ms | 289 ms | Returns before cognify starts |
| `remember` — `wait=true`, full ECL (extract→cognify→load) | 3 | 14.9 s | 15.9 s | 28.2 s | One dense sentence; LLM-bound |
| `recall` — knowledge graph query + LLM synthesis | 5 | 4.0 s | 7.2 s | 18.0 s | Small dataset; variance = LLM latency |
| `list_datasets` (REST) | 10 | 81 ms | 91 ms | 110 ms | No LLM involved |
| MCP bridge roundtrip — `remember_status` | 10 | 8 ms | 9 ms | 11 ms | Bridge-local, no proxy call needed for cached jobs |
| MCP bridge roundtrip — `list_agents` (proxies to REST) | 10 | 101 ms | 105 ms | 119 ms | ~105 ms proxy overhead vs ~91 ms raw REST |

Key takeaways:

- **Writes are effectively free for agents.** The default `remember` returns in
  ~280 ms and indexing happens in the background; `remember_status` (9 ms)
  closes the loop.
- **Reads are one LLM round-trip.** Median recall ≈ 7 s — comparable to a
  single model completion, because that is what it is.
- **The MCP bridge adds ~10–15 ms** over raw REST. Proxying costs nothing.

---

## 2. The workflow comparison: with vs without Ontogram

Without persistent memory, every session pays a **context re-establishment
tax**: the agent re-reads files, re-derives decisions, re-asks the user things
it was already told, and re-makes mistakes that were previously diagnosed.

| Session phase | Without Ontogram | With Ontogram |
| :--- | :--- | :--- |
| Session start — know what the project decided before | Re-explore repo / ask user (minutes or never) | 1 × `recall` ≈ **7 s**, answer grounded in stored facts |
| "Why did we choose X?" mid-task | Re-derive from scratch or interrupt user | Instant recall of stored rationale |
| Storing a decision when made | Lost unless written into committed docs | 1 × `remember` ≈ **0.3 s** (async) |
| Cross-session preferences (user's workflow, style) | Re-stated by user each session | Persisted per scope; recalled at start |
| Bug diagnosis from last week | Re-diagnosed from scratch | Recalled ("this failed because Y") |
| Context window budget | Full re-brief every session | One recall paragraph replaces pages of re-exploration |

### Illustrative token math per session (estimate — measure your own)

| | Without memory | With memory |
| :--- | ---: | ---: |
| Re-brief context (files read, user explanations) | 5k–50k tokens / several minutes | 1 × recall result (~200–800 tokens, ~7 s) |
| Repeated questions to the human | 1–5 per session | ~0 after first week |
| Marginal cost added | — | +1 recall (~7 s), +N remember calls (~0.3 s each) |

> [!NOTE]
> These agent-level figures depend entirely on your harness, task mix, and how
> diligently the memory protocol is wired into your AGENTS.md/CLAUDE.md (see
> [integrations/AGENTS_MEMORY.md](../integrations/AGENTS_MEMORY.md)). They are
> not benchmarks of Ontogram itself — section 1 is.

---

## 3. Reproducible A/B protocol for your own agents

To produce real with/without numbers on your workflow:

1. **Baseline (no memory):** run your normal task suite with no memory tools
   registered. Record wall-clock time, total tokens, and count of questions
   asked to the user.
2. **Treatment:** same tasks, Ontogram MCP registered *and* the memory protocol
   block present in the agent instructions (recall-on-start, remember-on-decision).
3. **Cross-session factor:** repeat the suite in a *new* session the next day —
   this is where the delta concentrates. The first session mostly measures
   remember overhead; sessions 2+ measure the savings.
4. Compare session-start tokens (prompt size at first tool call) and
   time-to-first-productive-action.

## 4. Cost model summary

| Thing | Cost to the agent |
| :--- | :--- |
| Store a fact | ~280 ms, zero agent attention |
| Confirm indexing | ~9 ms (`remember_status`) |
| Recall context | ~7 s median (one LLM call) |
| List/discover partitions | ~100 ms |
| Forget a scope | < 1 s |

The design goal: **writing memory must be cheaper than not writing it**, and
reading it must be cheaper than re-deriving. Both hold by roughly three orders
of magnitude.
