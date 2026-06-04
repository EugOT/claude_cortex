"""StreamSource adapters over the store's proven chunked iterators.

Wraps an existing keyset / named-cursor iterator (``iter_hot_memories_chunked``,
``iter_memories_for_decay``, or any ``(chunk_size) -> Iterator[list]`` factory)
as a ``StreamSource``. These iterators already stream at a measured 74MB peak
RSS / ~49.5k rows/s on a 500k-row corpus — the proven primitive; this adapter
only re-exposes them under the pipeline's port.

Pure infrastructure — no core imports (depends only on the injected factory).
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

# A factory that, given a chunk size, returns a generator of row batches.
# e.g. ``lambda n: store.iter_memories_for_decay(chunk_size=n)``.
ChunkIterFactory = Callable[[int], Iterator[list[Any]]]


class CursorStreamSource:
    """Adapt a chunked-iterator factory to the ``StreamSource`` port.

    The factory MUST use keyset or server-side-cursor pagination (value-anchored
    boundaries), never OFFSET — OFFSET drifts under concurrent mutation.
    """

    def __init__(self, iter_factory: ChunkIterFactory) -> None:
        self._iter_factory = iter_factory

    def stream(self, max_batch: int) -> Iterator[list[Any]]:
        """Yield batches of at most ``max_batch`` rows from the wrapped iterator."""
        yield from self._iter_factory(max_batch)


class ListStreamSource:
    """Adapt an already-materialized list to the ``StreamSource`` port.

    For stages whose upstream is a bounded in-memory list (e.g. edge rows that
    a yet-to-be-paged fetcher returns whole). Slices the list into batches so
    the consumer side stays constant-memory; the list itself is the caller's
    bound. Prefer ``CursorStreamSource`` whenever the upstream can stream.
    """

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def stream(self, max_batch: int) -> Iterator[list[Any]]:
        for i in range(0, len(self._rows), max_batch):
            yield self._rows[i : i + max_batch]
