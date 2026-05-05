"""Liskov contract enforcement: every registered MCP tool returns a dict.

Issue #17 (PSGSupport) — three handlers (remember, recall, get_telemetry)
were JSON-encoding their return values to strings before FastMCP saw
them. FastMCP 2.x rejects strings when an ``output_schema`` is declared:

    structured_content must be a dict or None. Got str: '{...}'

The fix moved ``safe_handler`` to return a dict directly. This test
pins the invariant: every tool registered on the FastMCP instance
declares ``return_type == dict`` (or a strict subtype). A handler that
silently regresses to ``-> str`` will fail this test before it ships.
"""

from __future__ import annotations

import asyncio
import typing

import pytest
from fastmcp import FastMCP

from mcp_server import (
    tool_registry_advanced,
    tool_registry_core,
    tool_registry_ingest,
    tool_registry_manage,
    tool_registry_memory,
    tool_registry_nav,
    tool_registry_wiki,
)


def _build_mcp_with_all_tools() -> FastMCP:
    """Construct a FastMCP instance with every tool registered.

    Mirrors mcp_server.__main__ so the test exercises the production
    registration path. No I/O or DB is touched at registration time;
    handlers are only constructed, not invoked.
    """
    mcp = FastMCP(name="contract-test", version="0.0.0")
    tool_registry_core.register(mcp)
    tool_registry_memory.register(mcp)
    tool_registry_manage.register(mcp)
    tool_registry_nav.register(mcp)
    tool_registry_advanced.register(mcp)
    tool_registry_wiki.register(mcp)
    tool_registry_ingest.register(mcp)
    return mcp


def _is_dict_return_type(return_type: typing.Any) -> bool:
    """True iff ``return_type`` is ``dict`` or a parametrized dict alias."""
    if return_type is dict:
        return True
    origin = typing.get_origin(return_type)
    return origin is dict


@pytest.fixture(scope="module")
def all_registered_tools():
    mcp = _build_mcp_with_all_tools()
    return asyncio.run(mcp.list_tools())


def test_at_least_one_tool_registered(all_registered_tools):
    """Sanity: registration produced tools (otherwise the test is vacuous)."""
    assert len(all_registered_tools) > 0


def test_every_tool_declares_dict_return_type(all_registered_tools):
    """Liskov: every MCP tool returns a dict, not a str.

    Issue #17 root cause: ``safe_handler`` JSON-encoded the dict before
    return, breaking the contract for handlers that declare
    ``output_schema``. This assertion fails the build if any new
    handler regresses to ``-> str``.
    """
    offenders = []
    for tool in all_registered_tools:
        rt = getattr(tool, "return_type", None)
        if not _is_dict_return_type(rt):
            offenders.append((tool.name, rt))

    assert not offenders, (
        "These handlers do not return a dict (issue #17 contract):\n"
        + "\n".join(f"  - {name}: {rt!r}" for name, rt in offenders)
    )


def test_tools_with_output_schema_have_dict_return_type(all_registered_tools):
    """When ``output_schema`` is declared, FastMCP rejects non-dict returns.

    This is the exact failure PSGSupport hit. A handler that declares
    a schema but returns a string is shipping a runtime error.
    """
    offenders = []
    for tool in all_registered_tools:
        if getattr(tool, "output_schema", None) is None:
            continue
        rt = getattr(tool, "return_type", None)
        if not _is_dict_return_type(rt):
            offenders.append((tool.name, rt))

    assert not offenders, (
        "Handlers declare output_schema but do not return dict — "
        "FastMCP will reject these at runtime (issue #17):\n"
        + "\n".join(f"  - {name}: {rt!r}" for name, rt in offenders)
    )
