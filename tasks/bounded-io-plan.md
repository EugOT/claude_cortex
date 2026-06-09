# Ecosystem Bounded-I/O Plan — 2026-06-09

Goal: every MCP boundary in the ecosystem (Cortex, automatised-pipeline, prd-spec-generator,
zetetic-team-subagents, session-optimizer) is bounded — no single response, load, or write can
blow up the MCP frame (~1MB ceiling, measured in query_workflow_graph comments) or machine RAM.
Prior art: ~/.claude/plans/sharded-popping-harbor.md (AIMD BatchWriter, calibration protocol).

Evidence base: 5-agent parallel audit, 2026-06-09. Reproduction: recall(15) → 815KB,
query_methodology → 262KB, both exceeded MCP tool-result limits.

## Phase 0 — Quick wins, hours, no design risk — DONE 2026-06-10 (gate green: 3143 passed + invariants 18/18)
- [x] Cortex: recall response ships `results` ≡ `memories` byte-identical duplicate → remove one. (~50% payload cut) — commit 1810d29
- [x] Cortex: `pg_store_queries.py:180` `get_all_memories_for_decay` SELECT * no LIMIT → route through `iter_memories_for_decay` unconditionally. — commit 1810d29
- [x] Cortex: query_methodology `firedTriggers` (55.6% of 262KB) — dedupe repeated triggers, cap content per trigger; stop re-embedding hot memories + triggers inside `context` string (shipped twice today). — commit 1810d29
- [x] session-optimizer: `stop-context-guard.py` `readlines()` loads whole transcript → reverse seek, bounded tail scan. — commits bc5db50 + 70411a8
- [x] zetetic-team-subagents: 19 doc strings "Optional MCP server: ai-architect" → automatised-pipeline; plugin.json/marketplace.json emails. — commits 2ff6f7a + e405ff6

## Phase 1 — Response budgets at every MCP boundary (the core fix)
- [x] Cortex: per-memory content truncation + total payload budget in recall / query_methodology / unified_search / wiki_read responses. Truncated items carry `truncated: true` + memory_id; full content retrievable by id (recall `memory_id`+`content_offset`, wiki_read `offset`). Budget MEASURED 2026-06-10: Claude Code 2.1.170 binary — MAX_MCP_OUTPUT_TOKENS default 25000 tokens × 4 chars/token = 100,000 chars compact JSON; verified char-exact against a rejected 324,429-char recall response. → core/response_budget.py, env override CORTEX_MEMORY_MAX_RESPONSE_CHARS.
  - Committed f28d1f1 (3173 tests).
  - Safety factor 0.75 on the host cap (→ 75,000 chars): Python `len()` counts code points, the host counts UTF-16 units — non-BMP chars diverge 2:1, so an exactly-full payload can overshoot. Factor reused from ai-prd-builder ContextManager.swift (`contextWindowSize * 0.75`, commit 462de01) per author direction; guarantees no overshoot up to 1/3 non-BMP fraction.
  - Priority-weighted water-filling (not a blind hard cap): surviving budget allocated proportionally to retrieval `score` (recall, unified_search) / `heat` (query_methodology hot memories) — ContextDecomposer allocation, ai-prd-builder 462de01: least relevant slots condense first; equal weights = plain max-min fairness; truncated detail stays dynamically loadable by id/offset.
- [x] automatised-pipeline (Rust): byte-budget at the 4 MCP boundaries (`bound_values` in new src/response_budget.rs, serialized-size accumulation) instead of the planned `take(MAX_QUERY_ROWS)` in `execute_query` — 70+ internal callers need complete result sets; truncating the shared primitive would corrupt graph resolution. LIMIT in find_related_out/in Cypher + LIMIT-injection for caller Cypher in query_graph (`limit_injected` flag); get_impact/get_processes arrays bounded with `truncated` + `*_total` fields (dependents_total pre-truncation = true blast radius). 219 tests green. — commit 6c99eb1; follow-up 967545d: docs + invariant test that UTF-8-byte counting ≥ UTF-16 units ⇒ inherently conservative, no safety factor needed (121+99 tests)
- [x] prd-spec-generator: Zod size contracts on PrdInputBundle (per-field char + element caps, rejection not truncation), MAX_CLARIFICATION_TURNS=50, MAX_PIPELINE_ERRORS=50 with FIFO eviction + `errors_dropped` counter. 607 tests green. — commit cd356ad; follow-up e43f41a fixed the aggregate overshoot (per-field shares summed to ~165% of the 100k cap): `boundFullStateResponse` sheds least-relevant detail first (grounding/validation blobs → oldest clarifications → section bodies; never the error trail), every shed observable in `__bounded.applied` with re-fetch hints via new `format:"grounding"`/`format:"validation"` selectors; JS `.length` is UTF-16 units = exact host match, no safety factor needed. 617 tests green.

## Phase 2 — Write-side hygiene (root cause of memory pollution)
- [ ] post_tool_capture: re-introduce size gate (the 2026-05-17 "no truncation" directive caused 95.8% pollution + 60× scoring inversion). Design: store gist + pointer to raw artifact, not raw 93KB blobs. Decision needed: gist-extraction vs hard cap.
- [ ] Fix scoring inversion: auto-captures score 0.9 vs curated 0.015 — investigate scoring path, curated memories must outrank raw dumps.
- [ ] backfill/import: per-item size limit on extracted memories before remember_handler.

## Phase 3 — Concurrency governors
- [ ] Cortex mcp_client_pool: max-connections + per-server concurrency cap (the stated "follow-on" from pool-leak fix).
- [ ] automatised-pipeline: GraphStore singleton (OnceLock<Arc<RwLock>>) — stop re-deserializing whole graph per request; bounded concurrent opens.
- [ ] prd-spec-generator: global run semaphore; InMemoryRunStore eviction (TTL/max-runs); EvidenceRepository retention.

## Phase 4 — Execute sharded-popping-harbor plan (constant-memory pipeline)
- [ ] Phase A core ports (StreamSource/BatchSink/AdaptiveBatchController/BackpressurePipeline)
- [ ] Phase B calibration benchmark (no invented constants — measure B_min/B_max/W_target/row_bytes)
- [ ] Phase C migrate 6 subsystems (ingest writers first: kills 5k commits/page)

## Deferred decisions (user)
- [ ] Push the 5 unpushed rename commits (Cortex×2, automatised-pipeline, prd-spec-generator, zetetic-team-subagents).
- [ ] Agent duplication: zetetic-team-subagents vs reasoning plugin export identical 116 agents — pick canonical, make other a mirror.
- [ ] Restart Cortex MCP server to live-verify ingest fix (no hot-reload).

## Review
(to fill as phases complete)
