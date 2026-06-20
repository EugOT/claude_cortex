# Migrating from database_url to cortex_home

Native Cortex no longer connects to PostgreSQL. Memories, wiki pages, and checkpoints are stored in local files under the Cortex home directory.

## What changed

- `database_url` is deprecated and ignored by the native binary.
- `cortex_home` is the plugin setting for the local store directory.
- `CORTEX_HOME` is the equivalent environment variable for direct CLI or MCP use.
- If neither value is set, Cortex uses `CLAUDE_PLUGIN_DATA` when available, then `$HOME/.claude/methodology/native`.

## Compatibility behavior

Existing plugin configs may keep `database_url` during migration. The native binary accepts the deprecated setting through `CORTEX_DATABASE_URL`, writes a warning to stderr when it is non-empty, and continues with local file-backed storage.

## Migration steps

1. Choose a local storage directory for Cortex data.
2. Set the plugin `cortex_home` value to that directory, or set `CORTEX_HOME` for direct CLI/MCP invocation.
3. Leave `database_url` empty in new configs.
4. Remove old PostgreSQL secrets only after confirming no other service still uses them.

This repository does not update external dotfiles, 1Password, k3s, or Octelium configuration. Those changes belong in the relevant infrastructure repository as a separate scoped patch.
