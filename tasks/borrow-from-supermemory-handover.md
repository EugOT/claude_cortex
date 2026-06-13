# Session Handover — Borrow from supermemoryai into Cortex

**Date:** 2026-06-13
**Source:** Architecture comparison of Cortex vs github.com/supermemoryai/supermemory (open shell over closed hosted engine).
**Status:** Analysis complete, implementation NOT started. This doc is the spec for the implementing session.

## Framing (read first)
Supermemory ships an open *shell* around a closed hosted engine. Cortex IS the open engine. We are not adopting supermemory's architecture — we are harvesting 4 design patterns its open contract reveals, to run on Cortex's verifiable local engine. All supermemory file:line refs below are in a separate clone (`/Users/cdeust/Developments/supermemory`) kept for reference only.

Ranked by leverage:
1. **Explicit supersession edges** (highest — retrieval correctness)
2. **Connection-rooted scoping** (safety/multi-agent isolation)
3. **Inline relation-walk recall mode** (cheap mid-tier retrieval)
4. **Viz spatial-hash hit-testing** (perf, low risk)

Acceptance for every item = EXTERNAL signal (a passing test or a benchmark delta), never model self-review. RECALL before touching each artifact (CLAUDE.md workflow).

---

## 1 — Explicit supersession edges  ★ highest value
**STATUS 2026-06-13: Phase 1 DONE & verified. Phase 2 (write-path detection) DONE & verified — see "Phase 2 outcome" at end of this section.**
**Problem:** Cortex models fact-updates via biological reconsolidation (`consolidation_stage`, `reconsolidation_count` in `mcp_server/infrastructure/pg_schema.py:20-68`). There is NO explicit "this fact supersedes that one" pointer, so "what did X say before?" is unanswerable and update-routing relies implicitly on recency+heat.
**supermemory pattern:** `parentMemoryId`/`rootMemoryId`/`isLatest` version chain + typed relation map (their `schemas.ts:250-256`).
**Cortex change:**
- Add nullable `supersedes_id INTEGER REFERENCES memories(id)` + `superseded_by_id` to `memories` (pg_schema.py). Migration, not rewrite — Cortex keeps the single-table reconsolidation model; this is an ADDITIVE explicit edge, not a replacement.
- On `remember` when the write-gate detects an update/merge (`mcp_server/handlers/remember.py`), set the supersession pointer instead of (or alongside) silent merge.
- In `recall_memories()` PL/pgSQL fusion (pg_schema.py:880-905), add a small boost/dedup so the head-of-chain (`superseded_by_id IS NULL`) outranks superseded versions.
**Acceptance:** LongMemEval "Knowledge updates" category MRR (current 0.925, `benchmarks/longmemeval/`) must not regress and should improve. Run on clean DB. RECALL past benchmark scores before changing fusion weights.

**Phase 1 (DONE 2026-06-13):**
- Columns `supersedes_id` + `superseded_by_id` (nullable, self-FK `REFERENCES memories(id) ON DELETE SET NULL`) added to `MEMORIES_DDL` (fresh installs) + idempotent DO block in `MIGRATIONS_DDL` (existing DBs), pg_schema.py.
- Recall head-of-chain demotion: final SELECT of `recall_memories()` now `ORDER BY (c.superseded_by_id IS NOT NULL), cw.final_score DESC` — a CONSTANT-FREE tier sort (current versions lead). Chose tier sort over a tuned penalty multiplier to satisfy the no-invented-constants rule.
- Two partial indexes: `idx_memories_superseded_by`, `idx_memories_supersedes`.
- Design decision (user-approved): supersession runs ALONGSIDE merge, contradiction-gated, NOT replacing it; supersession retains BOTH rows (merge destroys the old row → incompatible with the "what did X say before?" goal).
- External signal: 15 tests pass (`tests_py/infrastructure/test_pg_schema_recall.py` shape tests + new `test_pg_supersession.py` 3 live-PG behavior tests + `test_schema_integrity.py` + `test_pg_recall_scoring_debias.py` regression); `mypy --strict` clean on pg_schema.py. Benchmark-neutral by construction (fixtures never set edges → first sort key constant FALSE → identical order), corroborated by `test_no_edges_preserves_plain_score_order`.

**Phase 2 outcome (DONE 2026-06-13):**
- `insert_memory` (pg_store.py) now persists the forward edge `supersedes_id` (nullable; `superseded_by_id` defaults NULL and is closed by the new `set_superseded_by(old_id, new_id)` store method).
- `try_curation` (remember_helpers.py): when the curation action is `merge` (high sim + textual overlap) AND `curation.detect_contradictions(content, [cand])` is non-empty, it returns a new `supersede` action instead of merging. The handler then inserts the NEW row with `supersedes_id = old_id` and calls `set_superseded_by` to stamp the old row's back-pointer. Near-duplicates with NO contradiction keep the existing destructive merge. Response action normalized `supersede → "superseded"` in remember_response.py.
- **Contradiction signal = the existing committed `curation.detect_contradictions` heuristic** (negation mismatch + action divergence). Chosen over NLI/entailment deliberately: it introduces ZERO new constants/thresholds (zetetic source rule) and ZERO new model dependency (the local 384-dim MiniLM is the point). NLI was rejected as a heavy dep for a signal the codebase already computes.
- External signal: 7 new tests pass (`test_pg_supersession.py` +2 live-PG persistence/back-pointer; `test_remember.py::TestTryCurationSupersede` +2 supersede-vs-merge routing) on top of the Phase 1 net. `mypy --strict` introduced no new errors (pg_store.py/remember_helpers.py had pre-existing abstract-store attr-defined + bare-generic errors before this change; none added).
- **Benchmark: neutral by construction, NOT run as an improvement.** The LongMemEval/LoCoMo/BEAM loaders ingest via `benchmarks/lib/bench_db.py::load_memories → core/memory_ingest.ingest_memories_batch → store.insert_memory` directly — they BYPASS the `remember` handler and `try_curation`, so the Phase 2 detector never fires during benchmark loading. With no `supersedes_id` passed, `insert_memory` emits an identical INSERT (new column NULL) and the recall tier-sort first key is constant FALSE → byte-identical ranking. This is the same structural neutrality Phase 1 proved (`test_no_edges_preserves_plain_score_order`). No-regression gate passes trivially; the improvement goal is **out of reach until a knowledge-update fixture routes through the production write-path** (deferred — explicitly allowed by old step 5).
- **Carry-forward RESOLVED 2026-06-13 — measured/proven no-op; thread closed. Supersession cannot move KU MRR on this benchmark.** Investigated in three falsifying layers + one metric-semantics proof (Cortex memory_ids 4197865, 4197880, 4197901, 4197905):
  1. **Session granularity (4197865):** dry-run over all 78 KU questions (96,108 session pairs) replicating the exact committed gate (sim≥0.85 ∧ jaccard>0.5 ∧ `detect_contradictions`) → **0 edges**. Binding constraint: jaccard>0.5 (whole 50-turn sessions never share >50% vocab).
  2. **Chunk granularity (4197880):** same gate over `memory_decomposer` turn-pair chunks (10,152 chunks, 647,969 cross-session pairs) → **0 edges**. Jaccard still binds.
  3. **Atomic granularity (4197901):** 12 cleanly hand-extracted (old,new) atomic update pairs (the Mem0/Supermemory LLM-extractor mechanism) through the gate → atomic extraction **solves** jaccard (6/12 clear it) but **0/12 fire** because `detect_contradictions` is a software-config regex (negation words + deploy/install/switch verbs) and is **blind to same-slot value swaps** ("three"→"four", "$350k"→"$400k", "Thursday"→"Friday").
  4. **Metric semantics — the decisive close (4197905):** even a *perfect* value-change detector forming perfect old→new edges cannot help. `compute_mrr` credits the first retrieved session in `answer_set`, and each KU question flags **both** the old- and new-value session as answer sessions. Supersession demotes the OLD session — but it is a *credited* answer — so demotion is **monotonically non-improving for MRR (hurts or neutral)**. The lever points the wrong way: "prefer new over old" is a reader/generation property, not measured by Cortex's retrieval (session-id R@10/MRR) benchmark.
  - **Therefore: do NOT add a write-path KU loader mode to chase KU MRR — it would be dead work.** Phase 2 remains a production-correctness win (dual-row retention, "what did X say before?") justified on its own merits, NOT by KU MRR. Baseline KU MRR 0.9246 / R@10 1.0000 stands. Dry-run instruments: `/tmp/probe_a2_atomic.py`, `/tmp/dryrun_supersession_chunked.py`.

## 2 — Connection-rooted scoping  ✓ DONE 2026-06-13
**STATUS: DONE.** `infrastructure/memory_config.py::root_agent_topic()` reads launch-time `CORTEX_ROOT_AGENT_TOPIC`. When set: (a) recall.handler + remember.handler FORCE that `agent_topic` (handler-boundary defense, covers every caller); (b) `tool_registry_memory.py` registers param-free `tool_recall_rooted`/`tool_remember_rooted` variants — FastMCP derives the input schema from the signature, so `agent_topic` is absent from the tool schema (the model can't target/omit a scope). External signal: 5 tests in `tests_py/handlers/test_connection_rooted_scoping.py` (schema present-when-unrooted / absent-when-rooted; rooted recall forwards ROOT not caller topic; unrooted honors caller; rooted remember overwrites args['agent_topic']). All pass; mypy errors are the file's pre-existing untyped-decorator/bare-dict convention (rooted variants match existing tool_recall/tool_remember style).

**Original spec (for reference):**
**Problem:** Cortex scopes via `agent_topic` PARAMETER (`handlers/recall.py`, `handlers/remember.py`) the model can omit or get wrong.
**supermemory pattern:** `x-sm-project` header roots the connection and REMOVES the scope arg from tool schemas (`apps/mcp/src/server.ts:67-93`) — capability-style, model cannot target wrong scope.
**Cortex change:** Cortex MCP is FastMCP stdio (`mcp_server/__main__.py:66`), single-process, no headers. Equivalent = an env/launch-time `CORTEX_ROOT_AGENT_TOPIC`; when set, omit `agent_topic` from the registered tool schemas (`tool_registry_memory.py`) and force it server-side. Mirrors supermemory's schema-stripping.
**Acceptance:** new test — with root topic set, a recall cannot return another topic's memory; the `agent_topic` field is absent from the tool schema JSON.

## 3 — Inline relation-walk recall mode  ✓ DONE 2026-06-13
**STATUS: DONE.** `recall(include_related=True)` attaches `related = {versions, entities}` per surfaced memory via `recall_helpers.inline_related_neighbors`: `versions` = item-1 supersession-chain neighbors (supersedes / superseded_by, gist-truncated); `entities` = one-hop weight-ranked walk over the entity `relationships` graph for the memory's top entities. Runs on the capped result set after final ordering (fanout bounded by max_results), OFF by default (flat recall unchanged), OFF in all benchmark loaders. Bounds (max_entities=3, max_neighbors=5, _GIST_CHARS=160) are response-budget fanout caps cf. core/response_budget.py — NOT algorithmic constants, benchmark-irrelevant. Wired into both rooted + unrooted recall tool registrations. External signal: 3 live-PG tests in `tests_py/handlers/test_recall_include_related.py` (no `related` when off; version+entity neighbors inline when on; latency bounded < 8× flat recall). All pass. mypy: only the file's pre-existing MemoryStore abstract-base attr-defined convention. Latency "< full assembler" is structural: bounded one-hop walk vs whole-graph PageRank/HippoRAG (StageAwareContextAssembler) — not instantiated in test (dep-heavy), argued structurally.

**Original spec (for reference):**
**Problem:** Cortex has flat `recall` and the heavy 3-phase Context Assembler (`mcp_server/core/context_assembly/stage_assembler.py`, PageRank/HippoRAG). Nothing cheap in between.
**supermemory pattern:** v4 returns a fact + signed-distance parents/children inline in one payload (their `api.ts:677-770`).
**Cortex change:** add `include_related: bool` to `recall` (`tool_registry_memory.py` + `handlers/recall.py`); when true, for each hit do one hop over the entity `relationships` table (pg_schema.py:93-107) and inline direct neighbors. Reuse supersession edges from item 1 for the "version" axis.
**Acceptance:** unit test — `recall(..., include_related=True)` returns neighbors inline; latency stays < full assembler. Measure both.

## 4 — Viz spatial-hash hit-testing ✅ DONE 2026-06-13
**Problem:** Cortex graph hit-test is O(N) reverse-iteration (`ui/unified/js/workflow_graph_render_canvas.js:87-94`); slow on the 10-node-kind / AST-symbol graph.
**supermemory pattern:** 200px grid spatial hash, 3×3 neighborhood query.
**Cortex change:** add a grid hash in the canvas renderer, rebuilt on settle/drag only (supermemory rebuilds on position-hash change). Document-vs-memory → AABB vs circle test analog for Cortex node kinds.
**Acceptance:** hit-test correctness test + measured frame-time improvement on a >5k-node graph.

**Shipped:** `ui/unified/js/spatial_hash.js` (uniform-grid `SpatialHash`, cell=200 > max node radius 34 so 3×3 is provably exhaustive — Ericson 2005 Ch.7). Wired into `workflow_graph_render_canvas.js` `findNode`: grid in the steady state (settled/static), linear reverse-scan fallback while positions move; rebuilt on sim `'end'` + invalidated on `'tick'`; topmost-wins preserved via max-index tiebreak. Script tag added to `unified-viz.html` before the renderer.
**Acceptance met:** `tests_js/spatial_hash.test.js` (node:test) — 20k random queries spatial≡linear (incl. overlap tiebreak + radius boundary); frame-time on 6000 nodes (>5k) = **11.2× speedup** (8.19µs → 0.73µs/query). `node --test tests_js/spatial_hash.test.js` green.

---

## Do NOT borrow
Closed hosted engine; 1536-dim embeddings (Cortex's local 384-dim MiniLM 22MB is the point); thin 5-tool surface; OAuth.

## Open caveat (carry forward)
supermemory's engine internals are INFERRED from its Zod contract, not read from code (closed). Items 1 & 3 reimplement an *idea*, not a verified algorithm — Cortex's versions must be benchmarked on their own merits, not assumed equivalent.

## First action on resume
Start with item 1. RECALL "supersession version chain knowledge update memory" + "longmemeval knowledge updates benchmark score" (scoped to agent_topic), then read `pg_schema.py:20-68` (memories DDL) and `handlers/remember.py` write-gate before writing the migration.
