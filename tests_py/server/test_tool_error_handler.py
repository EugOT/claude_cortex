"""Tests for the MCP tool error boundary."""

from __future__ import annotations

import pytest

from mcp_server.observability import metrics
from mcp_server.tool_error_handler import (
    _classify_error,
    _dispatch_tool,
    _error_response,
    _hint_for_error,
    _run_inline,
    _run_tool_with_admission,
    _validate_args,
    safe_handler,
)


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


@pytest.mark.asyncio
async def test_safe_handler_dispatches_validated_args_with_defaults():
    async def handler(args):
        return args

    result = await safe_handler(handler, {}, tool_name="rebuild_profiles")

    assert result == {"force": False}


@pytest.mark.asyncio
async def test_safe_handler_validation_error_has_no_database_hint():
    metrics.reset()

    async def handler(args):
        return {"unreachable": True}

    result = await safe_handler(handler, {}, tool_name="remember")

    assert result["error"] == "ValidationError"
    assert result["hint"] is None
    assert result["details"] == {"tool": "remember", "field": "content"}
    rendered = metrics.render()
    assert 'cortex_tool_calls_total{status="error",tool="remember"} 1' in rendered


@pytest.mark.asyncio
async def test_safe_handler_without_tool_name_forwards_inline_args():
    async def handler(args):
        return {"got": args}

    result = await safe_handler(handler, {"inline": "payload"})

    assert result == {"got": {"inline": "payload"}}


def test_validate_args_forwards_original_payload():
    result = _validate_args("remember", {"content": "ok", "force": True})

    assert result["content"] == "ok"
    assert result["force"] is True


@pytest.mark.asyncio
async def test_run_tool_with_admission_records_exact_metric_contract():
    metrics.reset()

    async def handler(args):
        assert args == {"value": 7}
        return {"value": args["value"]}

    result = await _run_tool_with_admission("memory_stats", handler, {"value": 7})

    assert result == {"value": 7}
    rendered = metrics.render()
    assert 'cortex_tool_duration_seconds_count{tool="memory_stats"} 1' in rendered
    assert 'cortex_tool_calls_total{status="ok",tool="memory_stats"} 1' in rendered
    assert "XX" not in rendered


@pytest.mark.asyncio
async def test_run_inline_forwards_args():
    async def handler(args):
        return {"got": args}

    result = await _run_inline(handler, {"inline": True})

    assert result == {"got": {"inline": True}}


@pytest.mark.asyncio
async def test_dispatch_tool_validates_admits_and_normalizes():
    metrics.reset()

    async def handler(args):
        assert args == {"force": False}
        return None

    result = await _dispatch_tool(handler, {}, "rebuild_profiles")

    assert result == {}
    rendered = metrics.render()
    assert 'cortex_tool_calls_total{status="ok",tool="rebuild_profiles"} 1' in rendered


@pytest.mark.asyncio
async def test_dispatch_tool_inline_preserves_args():
    async def handler(args):
        assert args == {"inline": True}
        return {"ok": True}

    result = await _dispatch_tool(handler, {"inline": True}, None)

    assert result == {"ok": True}


def test_error_response_preserves_message_key_and_details():
    exc = ValueError("plain failure")

    response = _error_response(exc)

    assert response["error"] == "ValueError"
    assert response["message"] == "plain failure"
    assert "MESSAGE" not in response
    assert "XXmessageXX" not in response
    assert "details" not in response


def test_error_response_includes_validation_details():
    from mcp_server.errors import ValidationError

    response = _error_response(ValidationError("bad arg", {"field": "content"}))

    assert response["details"] == {"field": "content"}


@pytest.mark.parametrize(
    "error_type",
    ["missing_extension", "database_not_connected", "ValidationError"],
)
def test_hint_for_user_correctable_errors_is_none(error_type: str):
    assert _hint_for_error(error_type) is None


def test_hint_for_unknown_errors_keeps_database_guidance_text():
    assert (
        _hint_for_error("ValueError")
        == "If this persists, check that PostgreSQL is running "
        "and DATABASE_URL is set correctly."
    )
