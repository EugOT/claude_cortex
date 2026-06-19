# Ingest / codebase-analysis ecosystem — fix plan (2026-06-11)

Goal (user): `/cortex-visualize` must never show a stale/empty graph; the whole
AST + codebase-analysis pipeline must be **responsive, fast, and accurate** —
not just deadlock-free.

## Shipped (tested, pushed)
- **9c11be6** (released in 3.19.1, `4631868`) — deadlock SAFETY NET: `MCPClient`
  records `_bound_loop`; `connected` returns False on a closed/foreign loop so
  the pool reconnects instead of stranding the reader. `CORTEX_MCP_CALL_TIMEOUT_S`
  (default 600s) fails a wedged call loudly. 56 client tests pass.
- **b9c56c8** — STALE-GRAPH gate (item 2): `graph_is_fresh()` compares the graph
  artefact mtime vs newest source file (bounded ignore-pruned walk, early exit);
  `find_cached_graph` skips stale candidates → `ensure_graph` re-analyses. 30
  ingest tests pass. Scope: ingest only (viz roster resolver untouched).

## Remaining — needs a LIVE Cortex/AP MCP server to verify (it is disconnected now)

### A. Deadlock ROOT cause (architectural — highest priority)
The loop-liveness guard is a safety net, NOT the cause. Root: every MCP tool call
runs on a throwaway per-call event loop — `tool_error_handler._run_coroutine_on_thread`
(mcp_server/tool_error_handler.py:103) does `asyncio.new_event_loop()` →
`run_until_complete` → `loop.close()`. A pooled long-lived `MCPClient` (AP child)
has a persistent `_read_loop` task bound to whatever loop first connected it; on
reuse from a later per-call loop the reader is stranded → with the guard it now
*reconnects every call* (respawn/handshake churn — the user's "still slow / not
load-balanced" smell).
**Fix:** run the AP client's reader on a PERSISTENT background loop, decoupled
from per-call loops, so the connection is genuinely reused. The viz path already
does this — `mcp_server/infrastructure/ap_bridge.py` / `workflow_graph_source_ast.py`
`APBridge._ensure_loop` / `_run_forever`. Route the INGEST AP calls
(`ingest_helpers.call_upstream` → `mcp_client_pool.get_client`) through the same
persistent-loop bridge (or give `mcp_client_pool` a dedicated reader loop/thread).
Verify: two consecutive `ingest_codebase` calls in one session, second must NOT
reconnect and must NOT hang on a >64KB response. Regression test: a 256KB-response
fake child across two per-call loops with a SHARED persistent reader.

### B. Pipe-deadlock RCA (already logged)
See memory `ingest-codebase-pipe-deadlock-2026-06-11`. The >64KB OS pipe buffer is
the trigger; the dead-loop reader is the cause. Belongs with A.

### C. (item 1) Symbol-read producer/consumer overlap
`ingest_codebase._ingest_entities` fetches one 5,000-row symbol page then writes
it, SERIALLY (no overlap), while `_ingest_edges` uses `adaptive_drain(concurrency=2)`.
Entities are single-writer by necessity (dedup `NOT EXISTS ON LOWER(name)` races;
edges are safe via `ON CONFLICT DO NOTHING`). **Fix:** convert `_ingest_entities`
to `adaptive_drain(concurrency=1)` fed by an async `_symbol_pages()` generator —
overlap + AIMD batching, dedup-safe. TRADEOFF: drops the per-page crash-resume
checkpoint (`_checkpoint_read/write/clear`); entity writes are idempotent so
resume-from-scratch is safe, just redoes work. Unit-testable against the existing
`fake_upstream` fixture (no live AP needed). Smaller win than A.

### D. AST / analyze accuracy + responsiveness (the "whole ecosystem" demand)
- Reproduced 2026-06-11 on Cortex repo (force_reindex): analyze built 50,528 nodes
  / 50,515 edges in 32s, but the PG ingest truncated at offset 15000 on EOF and
  bound only 2,826 / 3,727 edges — i.e. partial ingest even when analyze is healthy.
  Once A lands, re-run and confirm full 50k symbol + edge binding.
- `resolution_rate: 0.26` from analyze (10,203 edges, 26% resolved) — investigate
  AST resolution accuracy (tree-sitter symbol→symbol binding) separately; low
  resolution = thin call graph even when ingest completes.
- `project_key` secondary bug: `project_key = path.name + hash` → the installed
  plugin path (leaf `3.19.0`) produces a graph keyed `3.19.0-...` instead of the
  project name. Confirm the viz ingests the user's PROJECT path, not the plugin
  cache path.

## Verification gates (all of A–D)
Clean DB + fresh analyze; two-call-in-a-session no-hang; full symbol/edge bind
count == analyze index counts; `/cortex-visualize` shows project clouds with L6
symbols + symbol→symbol edges; re-run after a source edit shows the change (no
stale serve).
