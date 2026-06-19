# Cortex Native

Cortex is a local memory server for Claude Code. This branch replaces the former Python and browser-JavaScript implementation with a native Zig command line and MCP server.

The native runtime is intentionally small:

- Zig 0.16 implementation only
- JSON-RPC MCP server over stdin/stdout
- File-backed local memory store
- Markdown wiki store
- Checkpoint save/restore
- Claude plugin metadata that launches the native binary directly
- No Python, JavaScript, package managers, generated wrappers, or runtime shims

## Build

Install Zig 0.16 or newer first; the Claude plugin `postInstall` step expects `zig` on `PATH`.

```sh
zig build
zig build test
```

## CLI

```sh
zig build run -- doctor
zig build run -- remember --content "Decision: keep Cortex native." --tag decision --force
zig build run -- recall --query "Cortex native"
zig build run -- stats
zig build run -- wiki write notes/native.md "# Native Cortex"
zig build run -- wiki read notes/native.md
```

Set `CORTEX_HOME` to choose the store directory. Without it, Cortex uses `CLAUDE_PLUGIN_DATA` when launched as a Claude plugin, otherwise `$HOME/.claude/methodology/native`.

The previous `database_url` plugin setting is deprecated and ignored by the native runtime. Existing plugin configs can leave it in place during migration, but new deployments should use `cortex_home` or `CORTEX_HOME`.

## MCP

```sh
zig build run -- mcp
```

The server supports `initialize`, `tools/list`, and `tools/call`. Core tools are implemented natively (`remember`, `recall`, `memory_stats`, `checkpoint`, and wiki tools). Advanced graph, visualization, benchmark, and external-ingest tools remain in the catalog for compatibility and return an explicit native status until their Zig implementations are added.

## Validation

```sh
zig build fmt
zig build check
zig build test
zig build docs
gitleaks detect --source . --config .gitleaks.toml --redact
git ls-files | grep -E '(\.(py|pyi|ipynb|js|mjs|cjs|jsx|ts|tsx)$|(^|/)(package\.json|pyproject\.toml|setup\.py|requirements\.txt|tox\.ini|pytest\.ini|tsconfig\.json|bun\.lock|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|pixi\.lock|uv\.lock)$)'
```

The final command must print nothing.
