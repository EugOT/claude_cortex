# Cortex Viz — Fix Status (2026-06-03)

Served viz = plugin cache `~/.claude/plugins/cache/cortex-plugins/cortex/3.18.3/`
spawned by `open_visualization` → `http_launcher.launch_server('unified')` on :3458.
Dev checkout `~/Developments/Cortex` is byte-identical to the cache for the
touched files. **These bugs were in current `main` (94fdc8e), not staleness.**

Fixes applied to BOTH dev + cache (verified no drift). NOT committed.

## DONE — 6 backend root-cause fixes

1. **`http_standalone.py` `_route_unified_get`** — wired 4 orphaned routes:
   `/api/graph`, `/api/graph/progress`, `/api/graph/events`, `/api/graph/phase`
   (only `/api/graph/node` was wired; frontend polls all four → got HTML).
   ✅ VERIFIED live: all return JSON. Root cause of "documents graph not
   functional / only first project / empty detail panel / progress stuck".
2. **`http_file_diff.py` `_git_root_for_name`** — stopped rejecting absolute
   paths (old code sent every `/...` path to `find_git_root()` with no arg →
   server CWD = plugin cache = not a repo → "not a git repo"). Now resolves the
   repo from the file's own absolute path, constrained to `_under_allowed_root`.
   ✅ VERIFIED live: real diffs (uncommitted 30 lines; new_file for .md).
3. **`http_standalone_trace.py` `_git_history` + `_git_versions`** — same
   no-arg `find_git_root()` bug; now use `_git_root_for_name(path)` +
   `resolve_file`. ✅ VERIFIED live: `git.available=True versions count=25`.
4. **`http_launcher.py` `_find_ap_binary`** — removed hardcoded
   `~/Documents/Developments/automatised-pipeline/...`; delegates to
   `pipeline_discovery.discover_pipeline_command()` (marketplace
   `installed_plugins.json` resolver, same as commit 94fdc8e). ✅ resolves AP
   0.2.2 marketplace binary.
5. **`http_launcher.py` `_detect_dev_source`** — removed hardcoded
   `~/Documents/Developments/Cortex` candidate. Client serves from install root
   via module walk-up; dev sync only via explicit `CORTEX_DEV_SOURCE_SYNC`.
6. **`http_standalone_graph.py`** — removed the global env mutation
   `os.environ['CORTEX_MEMORY_AP_ENABLED']='0'` + cache_clear during the
   baseline build (+ its now-empty try/finally restore). **Root cause of
   "AST ap_disabled / impact diagram never shows":** the build disabled AP
   process-wide for its whole multi-minute duration, so every interactive
   `/api/trace/impact` returned `ap_disabled` while a build was in flight. The
   build already defers AST via `defer_native_ast=True` (Phase 4 gated at
   `workflow_graph.py:661`), so the mutation was redundant + a §7.2
   global-mutable-state violation.

## ⚠️ ACTIVATION REQUIRED
The running Cortex MCP server loaded the OLD `http_launcher` at session start,
so `open_visualization` still spawns the viz WITHOUT `CORTEX_AP_COMMAND`.
**Reload the Cortex MCP server (restart Claude Code / reconnect MCP)** to pick
up the launcher fix — this is what makes the impact diagram actually reach AP,
and gives a fresh server + fresh PG pool.

## STILL BROKEN — next session

A. **Build STALLS at 28% "loading memories"** (node_count stuck 29; never
   reaches L4 discussions / L5 memories). This is the cause of "only first
   project shows / no memories+discussions on session click / legend count not
   in graph". Suspect PG connection starvation — this session leaked ~69 idle
   psycopg pools from kill-9'd test servers (`max_connections=100`, hit 98).
   First step: clean restart with drained PG; confirm stall is PG-starvation
   vs a genuinely slow 25k-of-500k memory query. If query: optimize/paginate.
B. **git diff / versioning "only code files"** — the ENDPOINTS work for any
   extension (verified .md), but file NODES are only created for code files.
   Non-code files touched by tools (L3 JSONL tool-event source) must become
   clickable nodes; verify `workflow_graph_source_jsonl` file_path → node and
   that the frontend opens diff/version panels for `kind=file` non-code nodes.
C. **discussions never showing** — `/api/discussions` returns data (disc_1…)
   but the frontend doesn't render them on session click. Wire session-click →
   memories + discussions in `ui/unified/js` (graph.js / detail_panel.js).
D. **can't return to wiki text from graph**; switching to the **trace** tab
   keeps showing the **wiki** graph — view/tab state bug in `ui/unified/js`.

## Integration directive (user)
Cortex → AP → prd-spec-generator must work as one system. Fix #4 makes the viz
use the SAME marketplace AP resolver as the pipeline. Remaining: audit that
every AP entry point (viz launcher, pipeline, ingest) routes through
`discover_pipeline_command()` — no second resolver, no hardcoded paths.

## DO NOT
Spawn competing standalone `http_standalone` servers to verify and kill-9 them
— it leaks psycopg pools → PG "too many clients" → stalls the real build.
Reuse the MCP-launched server, or do ONE controlled spawn with cleanup.
