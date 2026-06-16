"""SQLite extension-loading safety tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


class _RawConnection:
    def __init__(self) -> None:
        self.extension_states: list[bool] = []

    def enable_load_extension(self, enabled: bool) -> None:
        self.extension_states.append(enabled)


class _CompatConnection:
    def execute(self, sql: str) -> None:
        raise AssertionError(f"DDL should not run after load failure: {sql}")

    def commit(self) -> None:
        raise AssertionError("commit should not run after load failure")


def test_try_load_vec_disables_extension_after_load_failure():
    store = SqliteMemoryStore.__new__(SqliteMemoryStore)
    raw_conn = _RawConnection()
    store._raw_conn = raw_conn
    store._conn = _CompatConnection()
    store._has_vec = True
    sqlite_vec = SimpleNamespace(load=MagicMock(side_effect=RuntimeError("boom")))

    with patch.dict("sys.modules", {"sqlite_vec": sqlite_vec}):
        store._try_load_vec()

    assert raw_conn.extension_states == [True, False]
    assert store._has_vec is False
