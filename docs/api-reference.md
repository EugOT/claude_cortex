# Native MCP API Reference

Transport is newline-delimited JSON-RPC 2.0 over stdin/stdout.

## Implemented Native Tools

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

Advanced catalog entries remain visible for client compatibility. Unsupported
entries return `status: "not_implemented_native"` and must not be treated as
successful work.

## `remember`

Input:

- `content`
- optional `tags`
- optional `directory`
- optional `domain`
- optional `source`
- optional `force`
- optional `is_global`
- optional `supersedes`

Behavior:

- rejects empty content
- redacts obvious secrets and DSN credentials before persistence
- rejects near-duplicate content unless `force` is true
- writes one JSONL memory record

Output includes `stored`, `memory_id`, `action`, `reason`, `heat`,
`redacted`, `redaction_count`, and `supersedes`.

## `recall`

Input:

- `query`
- optional `domain`
- optional `directory`
- optional `max_results`
- optional `min_heat`
- optional `include_related`
- optional `include_superseded`

Behavior:

- scores with normalized lexical overlap, tag/domain evidence, heat, and prior
  access events
- hides superseded records by default
- appends access events for returned memories
- includes related records when requested

Output includes `memories`, `intent`, `count`, and optionally `related` and
`related_count`.

## `memory_stats`

Input: none.

Output: memory counts, lexical index count, supersession edge count, access
event count, redaction count, heat average, and native capability flags.

## `checkpoint`

Input: `action` (`save` or `restore`), `session_id`, and any additional fields
to persist.

Output: save/restore status and checkpoint content on restore.

## Graph Tools

`get_methodology_graph`, `query_workflow_graph`, and `navigate_memory` return
the native supersession graph: memory IDs as nodes and `new supersedes old`
edges.

## Wiki Tools

`wiki_write`, `wiki_read`, `wiki_list`, `wiki_reindex`, `wiki_adr`, and
`wiki_verify` operate on Markdown paths sandboxed under the native wiki root.

`wiki_link`, `wiki_purge`, and `wiki_rename` are visible for compatibility but
return `not_implemented_native`.
