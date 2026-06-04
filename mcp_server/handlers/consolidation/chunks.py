"""Shared helper: yield memory chunks for a consolidation stage.

Streams via the store's chunked decay cursor when available (PostgreSQL), so
peak RAM is one chunk. Falls back to a single materialized chunk when the
caller already holds a shared snapshot list (the consolidate handler's issue-13
one-load path) or when the store has no chunked cursor (SQLite / test fakes).
"""

from __future__ import annotations

from typing import Any, Iterable


def iter_memory_chunks(
    store: Any, memories: list[dict[str, Any]] | None
) -> Iterable[list[dict[str, Any]]]:
    """Return an iterable of memory chunks for a stage to reduce over.

    - ``memories is not None`` → ``[memories]`` (one chunk; caller's snapshot).
    - store has ``iter_memories_for_decay`` → the chunked server-side cursor.
    - otherwise → ``[store.get_all_memories_for_decay()]`` (compat fallback).
    """
    if memories is not None:
        return [memories]
    if hasattr(store, "iter_memories_for_decay"):
        return store.iter_memories_for_decay()
    return [store.get_all_memories_for_decay()]
