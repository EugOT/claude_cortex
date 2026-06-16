"""Friendly error handling for MCP tool calls.

Wraps handler exceptions so users never see raw Python tracebacks.
Database connection errors get a helpful setup guide instead.

Phase 5 adds two transparent safety nets on top of error handling:
  * per-tool admission semaphore (Phase 5 step 5)
  * asyncio.to_thread offload so handler bodies (which call sync
    DB methods) run on a worker thread instead of blocking the event
    loop

Issue #17 (PSGSupport): handlers that declare ``output_schema`` were
rejected by FastMCP with ``structured_content must be a dict or None.
Got str: '{...}'`` because this wrapper used to ``json.dumps`` the
result before returning. FastMCP 2.x validates the return shape
against the declared schema and rejects strings. Fix: return the
dict directly. The handler contract IS dict-or-None (Liskov: every
``mcp__cortex__*`` handler now uniformly satisfies the same interface).

Usage in tool registries:
    from mcp_server.tool_error_handler import safe_handler

    async def tool_remember(...) -> dict:
        result = await safe_handler(remember.handler, {...}, tool_name="remember")
        return result
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

_DB_SETUP_GUIDE = (
    "Cortex could not connect to PostgreSQL. "
    "This usually means the database is not set up yet.\n\n"
    "Quick fix:\n"
    "  brew install postgresql@17 pgvector\n"
    "  brew services start postgresql@17\n"
    "  createdb cortex\n"
    '  psql -d cortex -c "CREATE EXTENSION IF NOT EXISTS vector; '
    'CREATE EXTENSION IF NOT EXISTS pg_trgm;"\n'
    "  export DATABASE_URL=postgresql://localhost:5432/cortex\n\n"
    "Then restart Claude Code. Cortex will auto-initialize the schema."
)

_EXTENSION_GUIDE = (
    "Cortex requires the pgvector and pg_trgm PostgreSQL extensions.\n\n"
    "Install them:\n"
    "  brew install pgvector  # macOS\n"
    '  psql -d cortex -c "CREATE EXTENSION IF NOT EXISTS vector; '
    'CREATE EXTENSION IF NOT EXISTS pg_trgm;"\n\n'
    "Then restart Claude Code."
)


def _classify_error(exc: Exception) -> tuple[str, str]:
    """Classify an exception into a user-friendly category and message."""
    haystacks = (type(exc).__name__.lower(), str(exc).lower())

    if any(
        kw in haystack
        for kw in [
            'type "vector" does not exist',
            "extension",
            "pg_trgm",
        ]
        for haystack in haystacks
    ):
        return "missing_extension", _EXTENSION_GUIDE

    if any(
        kw in haystack
        for kw in [
            "connection refused",
            "could not connect",
            "no such host",
            "connection reset",
            "does not exist",
            "operationalerror",
            "role",
            "password authentication",
            "timeout",
        ]
        for haystack in haystacks
    ):
        return "database_not_connected", _DB_SETUP_GUIDE

    return type(exc).__name__, str(exc)


def _run_coroutine_on_thread(
    handler_fn: Callable[..., Awaitable[dict[str, Any] | None]],
    args: dict[str, Any],
) -> dict[str, Any] | None:
    """Run an async handler's coroutine on a fresh event loop in a worker thread.

    Used by ``safe_handler`` under ``asyncio.to_thread`` to give real
    parallelism when the handler body is effectively synchronous
    (calls sync store methods inside an ``async def``).

    Each worker thread gets its own event loop; no cross-thread loop
    sharing. The loop is closed at the end so thread reuse doesn't
    carry over state.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(handler_fn(args))
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _validate_args(tool_name: str | None, args: dict[str, Any]) -> dict[str, Any]:
    if not tool_name:
        return args
    from mcp_server.validation.schemas import validate_tool_args

    return validate_tool_args(tool_name, args)


async def _run_tool_with_admission(
    tool_name: str,
    handler_fn: Callable[..., Awaitable[dict[str, Any] | None]],
    args: dict[str, Any],
) -> dict[str, Any] | None:
    from mcp_server.handlers.admission import admit
    from mcp_server.observability import metrics

    async with admit(tool_name):
        with metrics.Timer("cortex_tool_duration_seconds", {"tool": tool_name}):
            result = await asyncio.to_thread(_run_coroutine_on_thread, handler_fn, args)
    metrics.inc_counter("cortex_tool_calls_total", {"tool": tool_name, "status": "ok"})
    return result


async def _run_inline(
    handler_fn: Callable[..., Awaitable[dict[str, Any] | None]],
    args: dict[str, Any],
) -> dict[str, Any] | None:
    return await handler_fn(args)


async def _dispatch_tool(
    handler_fn: Callable[..., Awaitable[dict[str, Any] | None]],
    args: dict[str, Any],
    tool_name: str | None,
) -> dict[str, Any]:
    call_args = _validate_args(tool_name, args)
    if tool_name:
        result = await _run_tool_with_admission(tool_name, handler_fn, call_args)
    else:
        result = await _run_inline(handler_fn, call_args)
    # Defensive: every handler must already return a dict per its
    # ``output_schema``. If a handler regresses to None we surface
    # an empty dict so FastMCP's structured-content validator does
    # not reject the response.
    normalized = _normalize_result(result)
    if not isinstance(normalized, dict):
        raise TypeError(
            f"Handler must return dict | None, got {type(normalized).__name__}"
        )
    return normalized


def _normalize_result(result: Any) -> Any:
    return {} if result is None else result


def _record_error_metrics(tool_name: str | None) -> None:
    if not tool_name:
        return
    try:
        from mcp_server.observability import metrics

        metrics.inc_counter(
            "cortex_tool_calls_total",
            {"tool": tool_name, "status": "error"},
        )
    except Exception:
        pass


def _error_response(exc: Exception) -> dict[str, Any]:
    error_type, message = _classify_error(exc)
    response: dict[str, Any] = {
        "error": error_type,
        "message": message,
        "hint": _hint_for_error(error_type),
    }
    details = getattr(exc, "details", None)
    if details:
        response["details"] = details
    return response


def _hint_for_error(error_type: str) -> str | None:
    if error_type in ("missing_extension", "database_not_connected", "ValidationError"):
        return None
    return (
        "If this persists, check that PostgreSQL is running "
        "and DATABASE_URL is set correctly."
    )


async def safe_handler(
    handler_fn: Callable[..., Awaitable[dict[str, Any] | None]],
    args: dict[str, Any],
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Call a handler and map exceptions into safe response dictionaries."""
    try:
        return await _dispatch_tool(handler_fn, args, tool_name)
    except Exception as exc:
        _record_error_metrics(tool_name)
        return _error_response(exc)
