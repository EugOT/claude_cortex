"""Backpressure pipeline — bounded-queue producer/consumer with constant peak RAM.

Pure orchestration logic — depends only on the StreamSource / BatchSink ports
(DIP); does no I/O itself. The injected sinks perform the writes.

Topology: one producer thread drains a StreamSource into a bounded queue;
``concurrency`` worker threads pull batches and call ``BatchSink.write_batch``.
The bounded queue with blocking ``put`` IS the backpressure mechanism (SEDA,
Welsh et al. 2001): when writers fall behind, the queue fills, the producer
blocks, and the source stops fetching. Peak resident payload is
``(queue_cap + concurrency + 1)`` batches — independent of total row count.

Shutdown: the producer emits exactly one sentinel per worker in a ``finally``
(so it fires on the crash path too); each worker consumes exactly one sentinel
and stops; the caller joins all workers before any pool is closed. There is no
other end-of-stream signal in the codebase, so this protocol is load-bearing.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from mcp_server.core.streaming.ports import BatchSink, StreamSource


@dataclass
class PipelineResult:
    """Outcome of one pipeline run (mutated under a lock by all threads)."""

    rows_in: int = 0
    rows_written: int = 0
    batches: int = 0
    errors: list[str] = field(default_factory=list)


class _Sentinel:
    """Poison pill — one is enqueued per worker to signal end-of-stream."""


_SENTINEL = _Sentinel()


def compute_queue_cap(
    ram_budget_bytes: int, b_max: int, row_bytes: int, reserve: int = 1
) -> int:
    """``Q_cap = floor(RAM_budget / (b_max * row_bytes)) - reserve``.

    Pinned to ``b_max`` (NOT the live B): the controller ramps B up to b_max,
    so sizing from a smaller live B would let peak RAM overshoot the budget by
    ``b_max / B`` once it ramps. source: Little (1961), occupancy bound applied
    to memory rather than time. Floors at 1 so the pipeline always makes
    progress.
    """
    if b_max <= 0 or row_bytes <= 0:
        raise ValueError("b_max and row_bytes must be positive")
    if ram_budget_bytes <= 0:
        raise ValueError("ram_budget_bytes must be positive")
    cap = ram_budget_bytes // (b_max * row_bytes) - reserve
    return max(1, cap)


@dataclass
class BackpressurePipeline:
    """Runs ``source -> bounded queue -> c x sink`` with bounded peak RAM.

    ``sink_factory`` builds ONE sink per worker — each worker owns its own
    connection (sharing a connection across threads is unsafe). The factory is
    injected by the handler (composition root) and binds the appropriate pool.
    """

    source: StreamSource
    sink_factory: Callable[[], BatchSink]
    max_batch: int
    queue_cap: int
    concurrency: int = 2

    def run(self) -> PipelineResult:
        """Drain the source through the workers; block until fully flushed.

        Postcondition: on return, every row the source yielded has been handed
        to a sink and durably committed (the staged barrier later phases rely
        on) OR surfaced in ``result.errors``.
        """
        q: queue.Queue[Any] = queue.Queue(maxsize=self.queue_cap)
        result = PipelineResult()
        lock = threading.Lock()
        producer = threading.Thread(
            target=self._produce, args=(q, result, lock), name="bp-producer"
        )
        workers = [
            threading.Thread(
                target=self._consume, args=(q, result, lock), name=f"bp-worker-{i}"
            )
            for i in range(self.concurrency)
        ]
        producer.start()
        for w in workers:
            w.start()
        producer.join()
        for w in workers:
            w.join()
        return result

    def _produce(
        self, q: "queue.Queue[Any]", result: PipelineResult, lock: threading.Lock
    ) -> None:
        try:
            for batch in self.source.stream(self.max_batch):
                q.put(batch)  # blocks when full — this is the backpressure
                with lock:
                    result.rows_in += len(batch)
                    result.batches += 1
        except Exception as exc:  # noqa: BLE001 — surfaced via result, not raised
            with lock:
                result.errors.append(f"producer: {exc!r}")
        finally:
            # Exactly one sentinel per worker — in finally so a producer crash
            # still releases every worker (no hang on an empty-but-open queue).
            for _ in range(self.concurrency):
                q.put(_SENTINEL)

    def _consume(
        self, q: "queue.Queue[Any]", result: PipelineResult, lock: threading.Lock
    ) -> None:
        sink = self._build_sink(result, lock)
        try:
            while True:
                item = q.get()
                if item is _SENTINEL:
                    return  # consumed our one sentinel — stop
                if sink is None:
                    continue  # setup failed; drain to our sentinel, don't hang
                self._write_one(sink, item, result, lock)
        finally:
            if sink is not None:
                self._close(sink, result, lock)

    def _build_sink(
        self, result: PipelineResult, lock: threading.Lock
    ) -> BatchSink | None:
        try:
            return self.sink_factory()
        except Exception as exc:  # noqa: BLE001
            with lock:
                result.errors.append(f"worker-setup: {exc!r}")
            return None

    @staticmethod
    def _write_one(
        sink: BatchSink,
        item: list[Any],
        result: PipelineResult,
        lock: threading.Lock,
    ) -> None:
        try:
            written = sink.write_batch(item)
            with lock:
                result.rows_written += written
        except Exception as exc:  # noqa: BLE001
            with lock:
                result.errors.append(f"worker: {exc!r}")

    @staticmethod
    def _close(sink: BatchSink, result: PipelineResult, lock: threading.Lock) -> None:
        try:
            sink.close()
        except Exception as exc:  # noqa: BLE001
            with lock:
                result.errors.append(f"worker-close: {exc!r}")
