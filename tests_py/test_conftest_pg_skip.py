"""Regression tests for PostgreSQL fallback collection filtering."""

from __future__ import annotations

from tests_py.conftest import _requires_live_pg


def test_pg_schema_only_files_are_not_skipped_in_sqlite_fallback() -> None:
    """Schema DDL tests do not need a live PostgreSQL connection."""
    assert not _requires_live_pg(
        "tests_py/infrastructure/test_pg_schema_recall.py::test_returns_columns"
    )
    assert not _requires_live_pg(
        "tests_py/infrastructure/test_pg_ingested_at.py::test_declares_column"
    )


def test_pg_fallback_compatible_store_tests_are_not_skipped() -> None:
    """Generic MemoryStore tests can run against SQLite fallback."""
    assert not _requires_live_pg(
        "tests_py/infrastructure/test_pg_store_delete_by_tag.py::test_scoped"
    )


def test_direct_pg_store_files_are_skipped_without_live_pg() -> None:
    """Files that instantiate PgMemoryStore still require reachable PostgreSQL."""
    assert _requires_live_pg(
        "tests_py/infrastructure/test_pg_pool.py::TestPoolLifecycle::test_pool"
    )
    assert _requires_live_pg(
        "tests_py/infrastructure/test_pg_user_mood.py::TestUserMoodWrite::test_set"
    )
    assert _requires_live_pg(
        "tests_py/infrastructure/test_pg_recall_scoring_debias.py::test_debias"
    )
