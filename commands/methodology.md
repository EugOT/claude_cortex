---
name: methodology
description: Inspect native Crtx memory status and retrieval context
---

Use the native MCP tool catalog:

1. Run `cortex:query_methodology` to get the current local-memory context.
2. Run `cortex:list_domains` to see domains present in the native JSONL store.
3. Run `cortex:get_methodology_graph` to inspect the native supersession graph.
4. Run `cortex:memory_stats` when safety, redaction, or access evidence matters.

If the store is empty, capture only concrete evidence with `cortex:remember`.
Avoid speculative cognitive-profile claims; the native rewrite preserves only
implemented retrieval, provenance, wiki, checkpoint, and supersession behavior.
