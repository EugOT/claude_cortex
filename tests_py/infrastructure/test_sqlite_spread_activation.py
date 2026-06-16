"""SQLite spread-activation query regressions."""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


def test_acquire_batch_commits_success_and_rolls_back_failure():
    store = SqliteMemoryStore(":memory:")
    try:
        memory_id = store.insert_memory(
            {"content": "SQLite batch parity", "importance": 0.1}
        )

        with store.acquire_batch() as conn:
            conn.execute(
                "UPDATE memories SET importance = %s WHERE id = %s",
                (0.7, memory_id),
            )

        assert store.get_memory(memory_id)["importance"] == 0.7

        with pytest.raises(RuntimeError, match="abort batch"):
            with store.acquire_batch() as conn:
                conn.execute(
                    "UPDATE memories SET importance = %s WHERE id = %s",
                    (0.2, memory_id),
                )
                raise RuntimeError("abort batch")

        assert store.get_memory(memory_id)["importance"] == 0.7
    finally:
        store.close()


def test_spread_activation_uses_entity_heat_and_memory_heat_base():
    store = SqliteMemoryStore(":memory:")
    try:
        store.insert_entity(
            {
                "name": "CortexSurface",
                "type": "concept",
                "heat": 0.9,
            }
        )
        memory_id = store.insert_memory(
            {
                "content": "CortexSurface validates spread activation heat columns",
                "heat": 0.8,
            }
        )

        results = store.spread_activation_memories(
            ["CortexSurface"],
            max_results=5,
            min_heat=0.05,
        )

        assert results == [(memory_id, 1.0)]
    finally:
        store.close()
