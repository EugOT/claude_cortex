"""Tests for the MCP tool error boundary."""

from __future__ import annotations

import pytest

from mcp_server.observability import metrics
from mcp_server.tool_error_handler import _classify_error, safe_handler


class OperationalErrorLike(Exception):
    """Exception whose type name is part of the classification contract."""


@pytest.mark.parametrize(
    "message",
    [
        'type "vector" does not exist',
        "extension pgvector is missing",
        "pg_trgm extension unavailable",
        "pg_trgm catalog missing",
    ],
)
def test_classifies_missing_extension_keywords(message: str):
    error_type, guide = _classify_error(Exception(message))

    assert error_type == "missing_extension"
    assert "pgvector" in guide


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionError("connection refused"),
        RuntimeError("could not connect to server"),
        OSError("no such host"),
        ConnectionResetError("connection reset"),
        RuntimeError("database does not exist"),
        OperationalErrorLike(""),
        RuntimeError("role cortex does not exist"),
        RuntimeError("role lookup failed"),
        RuntimeError("password authentication failed"),
        TimeoutError("timeout waiting for database"),
    ],
)
def test_classifies_database_connection_keywords(exc: Exception):
    error_type, guide = _classify_error(exc)

    assert error_type == "database_not_connected"
    assert "PostgreSQL" in guide


@pytest.mark.asyncio
async def test_safe_handler_success_increments_ok_counter():
    metrics.reset()

    async def good_handler(args):
        return {"status": "ok"}

    result = await safe_handler(good_handler, {}, tool_name="memory_stats")

    assert result == {"status": "ok"}
    rendered = metrics.render()
    assert 'cortex_tool_calls_total{status="ok",tool="memory_stats"} 1' in rendered
    assert 'cortex_tool_duration_seconds_count{tool="memory_stats"} 1' in rendered


@pytest.mark.asyncio
async def test_safe_handler_error_increments_error_counter():
    metrics.reset()

    async def failing_handler(args):
        raise ValueError("boom")

    result = await safe_handler(failing_handler, {}, tool_name="memory_stats")

    assert result["error"] == "ValueError"
    assert (
        result["hint"] == "If this persists, check that PostgreSQL is running "
        "and DATABASE_URL is set correctly."
    )
    rendered = metrics.render()
    assert 'cortex_tool_calls_total{status="error",tool="memory_stats"} 1' in rendered
