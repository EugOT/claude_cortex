# Crtx Native Agent Notes

Crtx is now a native Zig CLI and MCP server. The repository must not regain
Python or JavaScript implementation code, runtime package files, test harnesses,
or generated wrappers.

## Current Architecture

- `src/main.zig`: process entrypoint.
- `src/cortex.zig`: native store, retrieval, safety gates, MCP dispatcher, wiki,
  checkpoints, and unit tests.
- `src/tests.zig`: functional and MCP dispatcher tests.
- `build.zig`: native format, compile, test, and docs steps.
- `.claude-plugin/`: plugin metadata that launches `zig-out/bin/cortex` directly.

## Native Behavior

- Memory writes are local JSONL records under `CORTEX_HOME`, Claude plugin data,
  or the default user data directory.
- Writes redact obvious secrets and DSN credentials before persistence.
- Writes reject near-duplicate content by default using normalized lexical
  Jaccard similarity; callers must pass `force` to store a duplicate knowingly.
- Recall uses lexical overlap, tags, domain, heat, and access reinforcement.
- Superseded memories are hidden by default and can be included explicitly.
- The graph surface is the native supersession graph. Do not claim vector,
  embedding, neuroscience, browser visualization, or database-backed behavior
  unless it is implemented in Zig and tested here.

## Quality Rules

- Keep behavior honest: unsupported compatibility tools return explicit native
  unsupported status, not successful no-ops.
- Keep I/O boundaries visible and testable.
- Use Zig 0.16 allocator discipline: explicit ownership, `defer`/`errdefer`,
  `std.ArrayList(T) = .empty`, and allocator arguments on list operations.
- Prefer deterministic, dependency-free logic for the core.
- Add tests for every safety or retrieval behavior change.
- Update docs and plugin metadata in the same change when user-visible behavior
  changes.

## Validation

Run before submitting:

```sh
zig build fmt
zig build check
zig build test
zig build test -Doptimize=ReleaseSafe
# Active Zig development overlay only until stable 0.16.0 fuzzer is fixed.
zig build test --fuzz=1 --test-timeout 30s
zig build docs
gitleaks detect --source . --config .gitleaks.toml --redact
```

Zero Python/JavaScript proof should include tracked files, shebangs, package
metadata, and runnable docs.
