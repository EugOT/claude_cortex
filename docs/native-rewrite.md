# Native Rewrite Plan

## Current Behavior

The previous implementation exposed Cortex as a Claude Code MCP plugin with memory write/recall, checkpoints, wiki authoring, visualization, codebase ingestion, benchmark harnesses, and lifecycle hooks. It was implemented with Python, Pixi packaging, PostgreSQL/pgvector integration, and browser JavaScript visualizations.

## Language Choice

Zig is the implementation language. It fits the requested native stack, keeps deployment to a single binary, supports explicit ownership and allocator discipline, and matches the user's `claude-zig-quality`, `ziglint`, and `zigdoc` ecosystem. Odin is not used because there is no retained graphics/UI surface. Swift is not used because the product is a cross-platform CLI/MCP server rather than macOS-native UI. Rust fallback is not justified.

## Native Architecture

- `src/main.zig`: CLI entrypoint.
- `src/cortex.zig`: native store, CLI command handlers, MCP JSON-RPC dispatcher, wiki/checkpoint operations, and tests for core invariants.
- `src/tests.zig`: functional and MCP dispatcher tests.
- `build.zig`: Zig build, format, compile, test, and docs steps.
- `.claude-plugin/plugin.json`: launches `zig-out/bin/cortex` directly after native build.

The native store uses local JSONL under `CORTEX_HOME` or Claude plugin data. This removes database-driver and package-manager risk while preserving local-only operation.

## Compatibility Strategy

Implemented natively:

- `remember`
- `recall`
- `memory_stats`
- `get_telemetry`
- `checkpoint`
- `detect_domain`
- `query_methodology`
- `record_session_end`
- `consolidate`
- `wiki_write`
- `wiki_read`
- `wiki_list`
- `wiki_reindex`
- `wiki_adr`
- `wiki_link`
- `wiki_verify`
- `wiki_purge`
- `wiki_rename`

Retained as explicit compatibility catalog entries pending native ports:

- codebase ingestion and change-impact analysis
- workflow/causal graph navigation
- hierarchical recall
- browser visualization
- benchmark-only neuroscience mechanisms

These calls do not shell out to the removed Python/JavaScript stack. They return a structured native status so clients fail visibly instead of running hidden compatibility code.

## Ecosystem Integration

- `chezmoi`: no direct dotfile changes are mixed into this repo. A future chezmoi patch should add a native Cortex workflow/shim only after the PR lands.
- `EugOT/warp`: the CLI is a single binary suitable for Warp workflows: `cortex doctor`, `cortex recall`, `cortex remember`, and `cortex mcp`.
- `EugOT/walcode`: integration boundary is the MCP JSON-RPC catalog and file-backed store. Walcode can call the native MCP server without Python/JS runtime setup.
- `EugOT/just_bash`: command behavior is deterministic and stdout JSON is shell-friendly for just_bash custom commands.
- `EugOT/zeroclaw`: compatible through the MCP tool catalog and JSON tool-call boundary.
- `EugOT/pi-mono`: no JavaScript dependency is added here; pi-mono can consume the MCP boundary externally.
- `EugOT/pz`: build style follows the Zig 0.16 `build.zig`/`build.zig.zon` pattern, with explicit `fmt`, `check`, `test`, and `docs` steps.
- `claude-zig-quality`: use as an external gate; do not vendor its Bun/TypeScript scripts into this repository.
- `EugOT/ziglint`: `.ziglint.zon` is present for external lint runs.
- `EugOT/zigdoc`: `zig build docs` emits native Zig docs.

## Validation Plan

- `zig build fmt`
- `zig build check`
- `zig build test`
- `zig build docs`
- `gitleaks detect --source . --config .gitleaks.toml --redact`
- `veles` scan when available
- `claude-zig-quality verify-fast` as an external gate when the wrapper supports this checkout
- `ziglint` if available in `mise` or PATH
- zero Python/JavaScript proof with `git ls-files`, `find`, and `rg`

## Python/JavaScript Removal Plan

Removed:

- Python package metadata and lockfiles
- Python implementation and tests
- Python benchmark harnesses
- Python/JavaScript Claude config helpers
- browser JavaScript UI
- Python/Node Docker and CI paths
- runnable docs that instructed Python/JavaScript commands

The final repository must keep no tracked `.py`, `.js`, `.ts`, package files, Python/JS shebangs, or docs that make Python/JS part of the product.
