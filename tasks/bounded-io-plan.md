# Ecosystem Bounded-I/O Plan — 2026-06-09

Goal: every MCP boundary in the ecosystem (Cortex, automatised-pipeline, prd-spec-generator,
zetetic-team-subagents, session-optimizer) is bounded — no single response, load, or write can
blow up the MCP frame (~1MB ceiling, measured in query_workflow_graph comments) or machine RAM.
Prior art: ~/.claude/plans/sharded-popping-harbor.md (AIMD BatchWriter, calibration protocol).

Evidence base: 5-agent parallel audit, 2026-06-09. Reproduction: recall(15) → 815KB,
query_methodology → 262KB, both exceeded MCP tool-result limits.

## Phase 0 — Quick wins, hours, no design risk
- [ ] Cortex: recall response ships `results` ≡ `memories` byte-identical duplicate → remove one. (~50% payload cut)
- [ ] Cortex: `pg_store_queries.py:180` `get_all_memories_for_decay` SELECT * no LIMIT → route through `iter_memories_for_decay` unconditionally.
- [ ] Cortex: query_methodology `firedTriggers` (55.6% of 262KB) — dedupe repeated triggers, cap content per trigger; stop re-embedding hot memories + triggers inside `context` string (shipped twice today).
- [ ] session-optimizer: `stop-context-guard.py` `readlines()` loads whole transcript → reverse seek, bounded tail scan.
- [ ] zetetic-team-subagents: 19 doc strings "Optional MCP server: ai-architect" → automatised-pipeline; plugin.json/marketplace.json emails.

## Phase 1 — Response budgets at every MCP boundary (the core fix)
- [ ] Cortex: per-memory content truncation + total payload budget in recall / query_methodology / unified_search / wiki_read responses. Truncated items carry `truncated: true` + memory_id; full content retrievable by id. Budget value: MEASURE against MCP frame ceiling, no invented constants.
- [ ] automatised-pipeline (Rust): `take(MAX_QUERY_ROWS)` in `execute_query` (graph_store.rs:290); LIMIT in find_related_out/in Cypher (search/mod.rs:775–829); cap get_impact/get_processes arrays; LIMIT injection for caller Cypher in query_graph.
- [ ] prd-spec-generator: Zod size contracts on PrdInputBundle unknown fields; cap clarifications/errors arrays.

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
