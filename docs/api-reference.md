# Native MCP API Reference

Transport is newline-delimited JSON-RPC 2.0 over stdin/stdout.

Implemented native tools:

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

Advanced catalog entries remain visible for client compatibility. They return `status: "not_implemented_native"` until ported to Zig.

## `remember`

Input: `content`, optional `tags`, `directory`, `domain`, `source`, `force`, `is_global`.

Output: `stored`, `memory_id`, `action`, `reason`, `heat`.

## `recall`

Input: `query`, optional `domain`, `directory`, `max_results`, `min_heat`.

Output: `memories`, `intent`, `count`.

## `memory_stats`

Input: none.

Output: memory counts, heat average, and native capability flags.

## `checkpoint`

Input: `action` (`save` or `restore`), `session_id`, and any additional fields to persist.

Output: save/restore status and checkpoint content on restore.

## Wiki Tools

`wiki_write`, `wiki_read`, `wiki_list`, `wiki_reindex`, `wiki_adr`, `wiki_link`, `wiki_verify`, `wiki_purge`, and `wiki_rename` operate on Markdown paths sandboxed under the native wiki root.
