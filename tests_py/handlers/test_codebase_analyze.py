"""Tests for codebase_analyze handler internals."""

from __future__ import annotations

from types import SimpleNamespace

from mcp_server.handlers import codebase_analyze


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[int, ...]]] = []

    def execute(self, sql: str, params: tuple[int, ...]) -> None:
        self.executed.append((sql, params))


class _FakeBatch:
    def __init__(self, conn: _FakeConnection) -> None:
        self.conn = conn

    def __enter__(self) -> _FakeConnection:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeStore:
    def __init__(self) -> None:
        self.conn = _FakeConnection()
        self.bumped: list[tuple[int, float]] = []

    def acquire_batch(self) -> _FakeBatch:
        return _FakeBatch(self.conn)

    def bump_heat_raw(self, memory_id: int, amount: float) -> None:
        self.bumped.append((memory_id, amount))


class _FailingStore:
    def acquire_batch(self):
        raise RuntimeError("batch unavailable")

    def bump_heat_raw(self, memory_id: int, amount: float) -> None:
        raise AssertionError("heat boost should not run after batch failure")


def test_set_memory_metadata_uses_configured_heat_boost(monkeypatch):
    store = _FakeStore()
    settings = SimpleNamespace(
        CODEBASE_ANALYZE_HEAT_BOOST=0.42,
    )
    monkeypatch.setattr(codebase_analyze, "get_memory_settings", lambda: settings)

    codebase_analyze._set_memory_metadata(store, 123)

    assert store.bumped == [(123, 0.42)]
    assert "store_type = 'semantic'" in store.conn.executed[0][0]
    assert "importance" not in store.conn.executed[0][0]
    assert store.conn.executed[0][1] == (123,)


def test_schema_declares_write_annotation():
    assert codebase_analyze.schema["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }


def test_set_memory_metadata_logs_batch_failures(capsys):
    codebase_analyze._set_memory_metadata(_FailingStore(), 321)

    captured = capsys.readouterr()
    assert "metadata update failed for memory_id=321" in captured.err
    assert "batch unavailable" in captured.err
