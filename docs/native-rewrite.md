# Native Rewrite Plan

## Observation Stamp

- Host: `Evgeniis-MacBook-Pro`
- UTC: `2026-06-21T14:51:54Z`
- Repo path: `/Users/etretiakov/.codex/worktrees/fc00/claude_cortex`
- Branch: `test/crtx-post-merge-audit-20260621`
- HEAD at observation: `e87d9d33ae7146fb61922124a443f7b54f122ad7`
- Origin: `https://github.com/EugOT/Crtx.git`
- Upstream: `https://github.com/cdeust/Cortex.git`
- Dirty status: clean at observation
- Detected tracked implementation languages: Zig only

## Post-Merge Audit Update

PR #5 rewrote Crtx as native Zig and was merged to `dev` on 2026-06-20. PR #7
promoted `dev` to `main` as merge commit `e87d9d33`. PR #6, the upstream
sync PR, was closed unmerged because its direct merge would restore removed
dynamic-runtime code and undo the native rewrite.

The post-merge audit keeps the native rewrite as the source of truth and only
cherry-picks upstream ideas when they can be implemented natively without
Python, JavaScript, package managers, dynamic-runtime wrappers, or unsupported
behavior claims.

Current follow-up fixes:

- keep MCP `tools/call` robust on Zig 0.16-dev where `std.json.ObjectMap.empty`
  is no longer available
- add a native fuzz target for redaction, tokenization, fingerprinting, and
  lexical scoring
- add deterministic MCP JSON-RPC regression tests for missing, null, and scalar
  `arguments` values across the advertised tool catalog
- return native tool execution failures as JSON-RPC errors at the `handleRpc`
  boundary instead of relying on the outer stdio loop
- run the test suite in `ReleaseSafe` as a safety-mode rotation
- add the `ReleaseSafe` gate to CI and document the bounded fuzz gate for the
  active Zig development overlay

## Current Behavior

The native rewrite exposes Crtx as a Claude Code MCP plugin with memory
write/recall, checkpoints, wiki authoring, native supersession graph output,
domain listing, lifecycle hooks, and local diagnostics.

Historical Python, JavaScript, PostgreSQL, browser visualization, and benchmark
harnesses were removed. Upstream PR #6 is kept as evidence for functionality
themes, but it still imports dynamic-runtime code and cannot be merged into this
native rewrite as-is.

## Language Choice

Zig is the implementation language. It fits the requested native stack, keeps
deployment to a single binary, supports explicit ownership and allocator
discipline, and matches the user's `claude-zig-quality`, `ziglint`, and
`zigdoc` ecosystem.

Odin is not used because there is no retained graphics/UI surface. Swift is not
used because the product is a cross-platform CLI/MCP server rather than
macOS-native UI. Rust fallback is not justified.

## Native Architecture

- `src/main.zig`: CLI entrypoint.
- `src/cortex.zig`: native store, safety gates, retrieval scoring, MCP
  JSON-RPC dispatcher, wiki/checkpoint operations, and unit tests.
- `src/tests.zig`: functional and MCP dispatcher tests.
- `build.zig`: Zig build, format, compile, test, and docs steps.
- `.claude-plugin/plugin.json`: launches `zig-out/bin/cortex` directly after
  native build.

The native store uses local JSONL under `CORTEX_HOME` or Claude plugin data.
This removes database-driver and package-manager risk while preserving
local-only operation.

## Evidence-Based Retained Functionality

Implemented natively:

- write admission: empty-content rejection and normalized lexical Jaccard
  duplicate suppression
- privacy gate: obvious secret and DSN redaction before persistence
- recall: lexical overlap, tags, domain, heat, and access-event reinforcement
- supersession: new memories can mark older memories as superseded; recall hides
  superseded records unless requested
- graph: supersession nodes and edges
- local provenance: append-only memory and access events
- wiki: sandboxed Markdown page write/read/list/ADR/verify
- checkpoints: save/restore by validated session ID
- plugin compatibility: deprecated `database_url` is accepted as an ignored
  value with a warning

Removed or unsupported until there is a native implementation and tests:

- browser visualization
- external codebase ingestion
- vector search and embedding claims
- PostgreSQL runtime behavior
- neuroscience mechanisms that are only metaphors or benchmark notes
- successful no-op compatibility shims for state-changing tools

## Compatibility Strategy

Implemented native tools:

- `remember`
- `recall`
- `unified_search`
- `memory_stats`
- `get_telemetry`
- `checkpoint`
- `detect_domain`
- `list_domains`
- `query_methodology`
- `get_methodology_graph`
- `query_workflow_graph`
- `navigate_memory`
- `record_session_end`
- `wiki_write`
- `wiki_read`
- `wiki_list`
- `wiki_reindex`
- `wiki_adr`
- `wiki_verify`

Compatibility catalog entries that are not implemented return
`status: "not_implemented_native"` and do not shell out to removed runtimes.

## Ecosystem Integration

- `chezmoi`: no direct dotfile changes are mixed into this repo. Context7's
  current chezmoi guidance reinforces a single source of truth and source-first
  edits with `chezmoi diff`/`chezmoi apply`; a future dotfiles patch should add
  any Crtx workflow/shim in `~/.local/share/chezmoi`.
- `nix-darwin`: Context7's current nix-darwin manual confirms packages belong
  in declarative system package/service configuration. Zig/Crtx installation
  should be added through the user's nix-darwin/chezmoi control plane, not by
  this application repo.
- `EugOT/warp`: the CLI is a single binary suitable for Warp workflows:
  `cortex doctor`, `cortex recall`, `cortex remember`, and `cortex mcp`.
- `EugOT/walcode`: integration boundary is the MCP JSON-RPC catalog and
  file-backed store. Walcode can call the native MCP server without dynamic
  runtime setup.
- `EugOT/just_bash`: command behavior is deterministic and stdout JSON is
  shell-friendly for just_bash custom commands.
- `EugOT/zeroclaw`: compatible through the MCP tool catalog and JSON tool-call
  boundary.
- `EugOT/pi-mono`: no frontend runtime dependency is added here; pi-mono can
  consume the MCP boundary externally.
- `EugOT/pz`: build style follows the Zig 0.16 `build.zig`/`build.zig.zon`
  pattern, with explicit `fmt`, `check`, `test`, and `docs` steps.
- `claude-zig-quality`: use as an external gate; do not vendor its auxiliary
  scripts into this repository.
- `EugOT/ziglint`: `.ziglint.zon` is present for external lint runs.
- `EugOT/zigdoc`: `zig build docs` emits native Zig docs.

## Validation Plan

- `zig build fmt`
- `zig build check`
- `zig build test`
- `zig build test -Doptimize=ReleaseSafe`
- `zig build test --fuzz=1 --test-timeout 30s` on the active Zig development
  overlay; `mise x zig@0.16.0` currently fails this fuzzer rebuild in Zig's
  compiler test runner
- `zig build docs`
- `gitleaks detect --source . --config .gitleaks.toml --redact`
- `veles` scan when available
- `claude-zig-quality` as an external gate when its verifier can be invoked
  without importing Bun/TypeScript tooling into this repository
- `ziglint` if available in `mise` or `PATH`
- `zigdoc` if available in `mise` or `PATH`; `zig build docs` remains the
  in-repo docs gate
- zero Python/JavaScript proof with `git ls-files`, `find`, and `rg`

Local post-merge validation on 2026-06-21 found these external limitations:

- `gitstore verify .` crashed in `/opt/homebrew/Cellar/gitstore/0.2.2/bin/gitstore`
  with `panic: reached unreachable code`
- this checkout is not a `jj` repository
- `veles`, `ziglint`, `zigdoc`, and a direct `claude-zig-quality` command were
  not present on `PATH`
- `mise x zig@0.16.0 -- zig build test --fuzz=1 --test-timeout 30s` failed in
  Zig's compiler test runner with a `builtin.StackTrace`/`debug.StackTrace`
  mismatch; stable `fmt`, `check`, and normal `test` passed
- Phoenix LiveView report host `http://100.100.39.44:4000` timed out from this
  MacBook; SSH to `himalayas` worked, but publishing the 7.3 KB report failed
  because the Data volume is at 100% and destination writes fail.

## Python/JavaScript Removal Plan

Removed:

- dynamic-runtime package metadata and lockfiles
- dynamic-runtime implementation and tests
- benchmark harnesses from the removed runtime
- Claude config helpers from the removed runtime
- browser UI
- Docker and CI paths for the removed runtimes
- runnable docs that instructed removed-runtime commands

The final repository must keep no tracked `.py`, `.js`, `.ts`, package files,
dynamic-runtime shebangs, or docs that make those runtimes part of the product.
