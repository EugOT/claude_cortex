"""Tests for ``workflow_graph_source_ast`` — C3 streaming + bounded waits.

Covers the sharded-popping-harbor C3 contract:
  * ``iter_symbols`` / ``iter_ast_edges`` yield one batch per AP query,
    incrementally — the consumer sees batch N before batch N+1's query is
    issued (fake bridge records fetch order vs. consumer position).
  * A wedged loop / never-completing future raises ``McpConnectionError``
    (bounded cross-loop wait) instead of hanging the worker.
  * No full-set materialization inside the source — peak retained rows
    across the stream is one batch, not the union of all queries.

HARD RULE (prior lesson): never mock ``asyncio.sleep`` for this transport —
a mocked sleep turns the idle loop into a busy-spin hang. These tests use a
real (tiny) sleep and a real bounded wait instead.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure import workflow_graph_source_ast as mod
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
    _SyncLoop,
)


@pytest.fixture(autouse=True)
def _enable_ap(monkeypatch):
    """Force AP enabled + a single graph path; isolate the timeout setting."""
    monkeypatch.setattr(mod, "is_enabled", lambda: True)
    monkeypatch.setattr(mod, "resolve_graph_paths", lambda: ["/fake/graph.kuzu"])
    monkeypatch.setattr(mod, "resolve_graph_path", lambda: "/fake/graph.kuzu")
    from mcp_server.infrastructure import memory_config

    memory_config.get_memory_settings.cache_clear()
    yield
    memory_config.get_memory_settings.cache_clear()


class _RecordingBridge:
    """Fake APBridge that records the ORDER in which queries are issued and
    returns a fixed row list per query. ``calls_at_yield`` lets a test assert
    how many queries had been issued at the moment the consumer pulled item k.

    Each ``query_graph`` returns rows in AP's ``{columns, rows}`` shape so the
    real ``_as_list`` path is exercised. Symbol queries get one synthetic
    symbol per label; edge queries get rows only for the first rel-table so we
    can keep the fixture small while still streaming many (mostly empty) ones.
    """

    def __init__(self, rows_per_query: int = 1) -> None:
        self.query_log: list[str] = []
        self._rows_per_query = rows_per_query

    async def call(self, tool: str, args: dict | None = None):
        assert tool == "query_graph"
        query = (args or {}).get("query", "")
        self.query_log.append(query)
        # Symbol queries: ``MATCH (s:Label) ... RETURN s.qualified_name ...``
        if "qualified_name AS qualified_name" in query or "s.id   AS" in query:
            rows = [
                ["pkg/mod.py::sym%d" % i, "sym%d" % i]
                for i in range(self._rows_per_query)
            ]
            return {"columns": ["qualified_name", "name"], "rows": rows}
        # Edge queries: ``MATCH (src)-[r:Table]->(dst) RETURN src_name, ...``.
        # Only the FIRST edge query returns rows; the rest are empty so the
        # batch count stays small but the stream still issues every query.
        if len(self.query_log) == 1 or "Calls_Function_Function" in query:
            rows = [["a::f", "b::g"] for _ in range(self._rows_per_query)]
            return {"columns": ["src_name", "dst_name"], "rows": rows}
        return {"columns": ["src_name", "dst_name"], "rows": []}

    async def close(self):
        return None


def _make_source(bridge) -> WorkflowGraphASTSource:
    src = WorkflowGraphASTSource(bridge=bridge)
    return src


class TestIncrementalYield:
    def test_symbols_yield_one_batch_per_query_in_order(self):
        """The consumer receives batch 1 strictly before batch 2's query is
        issued — proving per-query streaming, not a single fetch-all."""
        bridge = _RecordingBridge(rows_per_query=2)
        src = _make_source(bridge)
        try:
            seen_query_counts: list[int] = []
            batch_count = 0
            for batch in src.iter_symbols(["/abs/pkg/mod.py"]):
                # At the moment we receive a batch, the number of queries
                # issued so far is recorded. If the source fetched everything
                # up-front, this would equal the TOTAL query count on the very
                # first batch. Incremental streaming → it grows monotonically.
                seen_query_counts.append(len(bridge.query_log))
                batch_count += 1
                if batch_count >= 3:
                    break
            assert batch_count >= 1
            # Strictly increasing: each new batch corresponds to a new query
            # that was issued AFTER the previous batch was consumed.
            assert seen_query_counts == sorted(set(seen_query_counts))
            assert seen_query_counts[0] < len(mod._SYMBOL_LABELS)
        finally:
            src.close()

    def test_edges_yield_incrementally(self):
        bridge = _RecordingBridge(rows_per_query=1)
        src = _make_source(bridge)
        try:
            first_batch_query_count = None
            total = 0
            for _batch in src.iter_ast_edges([]):
                if first_batch_query_count is None:
                    first_batch_query_count = len(bridge.query_log)
                total += 1
            # The first non-empty batch arrived after only a handful of
            # queries — NOT after all ~89 edge queries completed.
            assert first_batch_query_count is not None
            assert first_batch_query_count < 89
        finally:
            src.close()


class TestNoFullMaterialization:
    def test_peak_retained_rows_is_one_batch(self):
        """The source never holds the union of all query results at once.

        We consume the stream but only keep a running max of the CURRENT
        batch size. With N queries each returning R rows, a fetch-all source
        would force a single list of N*R rows somewhere; the generator keeps
        peak retained (per the consumer's own bookkeeping) at R.
        """
        rows = 4
        bridge = _RecordingBridge(rows_per_query=rows)
        src = _make_source(bridge)
        try:
            peak_single_batch = 0
            batches_seen = 0
            for batch in src.iter_symbols(["/abs/pkg/mod.py"]):
                peak_single_batch = max(peak_single_batch, len(batch))
                batches_seen += 1
                # Drop the batch immediately (do NOT accumulate) — emulates a
                # streaming consumer. peak stays at one query's row count.
                del batch
            assert batches_seen >= 1
            assert peak_single_batch == rows
        finally:
            src.close()

    def test_load_symbols_full_set_still_works(self):
        """The list convenience API still returns the full set for genuine
        full-set consumers (builder + len())."""
        bridge = _RecordingBridge(rows_per_query=3)
        src = _make_source(bridge)
        try:
            allrows = src.load_symbols(["/abs/pkg/mod.py"])
            # 21 labels × 3 rows each (every label query returns rows here).
            assert len(allrows) == len(mod._SYMBOL_LABELS) * 3
            assert all("qualified_name" in r for r in allrows)
        finally:
            src.close()


class TestBoundedWaitTimeout:
    def test_run_raises_on_wedged_loop(self, monkeypatch):
        """A coroutine that never completes must raise McpConnectionError via
        the bounded cross-loop wait — not hang forever. Uses a tiny TEST
        timeout (a test constant, not production) and a REAL sleep (never a
        mocked asyncio.sleep — that would busy-spin the idle loop)."""
        import asyncio

        # Tiny timeout for the test only — production default is 3900 s.
        monkeypatch.setenv("CORTEX_MEMORY_AP_SYNC_RESULT_TIMEOUT_S", "0.2")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()

        loop_owner = _SyncLoop()
        try:

            async def _never():
                # Real sleep, far longer than the 0.2 s wait ceiling.
                await asyncio.sleep(30)
                return "unreachable"

            with pytest.raises(McpConnectionError):
                loop_owner.run(_never())
        finally:
            loop_owner.close()

    def test_run_iter_raises_on_wedged_step(self, monkeypatch):
        """A streaming step that wedges raises McpConnectionError, and batches
        already yielded before the wedge are real (not silently truncated to a
        full list)."""
        import asyncio

        monkeypatch.setenv("CORTEX_MEMORY_AP_SYNC_RESULT_TIMEOUT_S", "0.2")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()

        loop_owner = _SyncLoop()
        try:

            async def _agen():
                yield [1, 2]
                yield [3, 4]
                await asyncio.sleep(30)  # wedge on the third step
                yield [5, 6]

            got: list = []
            with pytest.raises(McpConnectionError):
                for batch in loop_owner.run_iter(_agen()):
                    got.append(batch)
            # The two pre-wedge batches were really delivered.
            assert got == [[1, 2], [3, 4]]
        finally:
            loop_owner.close()


class TestSingleReaderOwnership:
    def test_one_loop_thread_owns_the_loop(self):
        """Document + verify single-reader ownership: one ap-sync-loop thread
        services every call (Lamport H4 — one reader over one pipe)."""
        import threading

        loop_owner = _SyncLoop()
        try:
            seen_threads: set[int] = set()

            async def _who():
                seen_threads.add(threading.get_ident())
                return threading.get_ident()

            t1 = loop_owner.run(_who())
            t2 = loop_owner.run(_who())
            # Both coroutines ran on the SAME (single) loop thread.
            assert t1 == t2
            assert len(seen_threads) == 1
            # And it is NOT the caller's thread.
            assert t1 != threading.get_ident()
        finally:
            loop_owner.close()


class TestDisabledDegradation:
    def test_iter_symbols_empty_when_disabled(self, monkeypatch):
        monkeypatch.setattr(mod, "is_enabled", lambda: False)
        src = _make_source(_RecordingBridge())
        try:
            assert list(src.iter_symbols(["/x.py"])) == []
            assert src.load_symbols(["/x.py"]) == []
        finally:
            src.close()
