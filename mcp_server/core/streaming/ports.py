"""Streaming pipeline ports — producer/consumer contracts.

Pure business logic — no I/O. Infrastructure implements these protocols
(CursorStreamSource, CopyBatchSink, ExecuteManyBatchSink, StagingResolveSink);
handlers wire them into a BackpressurePipeline.

The contracts encode the invariant that makes peak RAM independent of total
row count:
  - every producer is a generator yielding bounded batches, never a full list;
  - every consumer flushes one batch and releases it, never accumulating
    across batches (no stage-spanning buffer — not even a name->id map).
"""

from __future__ import annotations

from typing import Iterator, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class StreamSource(Protocol[T]):
    """A bounded-batch producer.

    Contract:
      - ``stream`` MUST be a generator; it never materializes the full result
        set. Peak resident rows from the source is one yielded batch.
      - Each yielded list is non-empty and ``len(batch) <= max_batch``.
      - Iteration order is deterministic (keyset / cursor order) so a consumer
        may record the last item and resume after an interruption. OFFSET
        pagination is forbidden — it drifts under concurrent mutation.
    """

    def stream(self, max_batch: int) -> Iterator[list[T]]:
        """Yield successive batches of at most ``max_batch`` items."""
        ...


@runtime_checkable
class BatchSink(Protocol[T]):
    """A batch consumer that durably writes one batch and releases it.

    Contract:
      - On normal return from ``write_batch``, every row in ``batch`` is
        durably committed and the underlying connection holds NO open
        transaction (commit state must not leak across the abstraction).
      - The sink MUST NOT retain references to rows after return — one batch
        in, one batch written, one batch's worth of RAM.
      - On failure ``write_batch`` raises; the batch is rolled back atomically
        (all-or-nothing). Under ``autocommit=True`` this requires the adapter
        to wrap the write in an explicit ``with conn.transaction():``.
      - ``write_batch`` returns the number of rows persisted; after dedup /
        ``ON CONFLICT DO NOTHING`` this may be smaller than ``len(batch)``.
    """

    def write_batch(self, batch: list[T]) -> int:
        """Durably write ``batch``; return the count persisted."""
        ...

    def close(self) -> None:
        """Release any borrowed resource (e.g. return a pooled connection).

        Idempotent — safe to call once per sink after its worker finishes.
        """
        ...
