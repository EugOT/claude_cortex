# Crtx Native

Crtx is a local memory server for Claude Code. This branch replaces the former
dynamic-runtime implementation with a native Zig command line and MCP server.

The retained native surface is deliberately narrow and evidence-based:

- Zig 0.16 implementation only
- JSON-RPC MCP server over stdin/stdout
- Local JSONL memory store
- Conservative write gate using normalized lexical Jaccard similarity
- Secret and DSN redaction before persistence
- Recall scoring with lexical overlap, tags, domain, heat, and access events
- Explicit supersession metadata and native supersession graph output
- Markdown wiki store
- Checkpoint save/restore
- Claude plugin metadata that launches the native binary directly
- No Python, JavaScript, package managers, generated wrappers, or runtime shims

Unsupported historical surfaces remain visible only where client compatibility
requires a tool name. They return explicit native unsupported status.

## Build

Install Zig 0.16 or newer first; the Claude plugin `postInstall` step expects
`zig` on `PATH`.

```sh
zig build
zig build test
```

## CLI

```sh
zig build run -- doctor
zig build run -- remember --content "Decision: keep Crtx native." --tag decision --force
zig build run -- recall --query "Crtx native" --include-related
zig build run -- stats
zig build run -- wiki write notes/native.md "# Native Crtx"
zig build run -- wiki read notes/native.md
```

Set `CORTEX_HOME` to choose the store directory. Without it, Crtx uses
`CLAUDE_PLUGIN_DATA` when launched as a Claude plugin, otherwise
`$HOME/.claude/methodology/native`.

The previous `database_url` plugin setting is deprecated and ignored by the
native runtime. Existing plugin configs can leave it in place during migration,
but new deployments should use `cortex_home` or `CORTEX_HOME`.

## MCP

```sh
zig build run -- mcp
```

The server supports `initialize`, `tools/list`, and `tools/call`.

Implemented core tools include `remember`, `recall`, `unified_search`,
`memory_stats`, `get_telemetry`, `checkpoint`, `detect_domain`, `list_domains`,
`get_methodology_graph`, `query_workflow_graph`, `navigate_memory`, and the
Markdown wiki tools.

## Validation

```sh
zig build fmt
zig build check
zig build test
zig build docs
gitleaks detect --source . --config .gitleaks.toml --redact
git ls-files | rg '(\.(py|pyi|ipynb|js|mjs|cjs|jsx|ts|tsx)$|(^|/)(package\.json|pyproject\.toml|setup\.py|requirements\.txt|tox\.ini|pytest\.ini|tsconfig\.json|bun\.lock|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|pixi\.lock|uv\.lock)$)'
```

The final command must print nothing.
