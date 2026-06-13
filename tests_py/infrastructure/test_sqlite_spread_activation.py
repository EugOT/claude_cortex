"""SQLite spread-activation query regressions."""

from __future__ import annotations

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


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
