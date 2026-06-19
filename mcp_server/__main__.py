"""Bootstrap entry point for the methodology-agent MCP server.

Uses FastMCP (3.x) for protocol handling — supports MCP 2025-11-25 natively.
Bridges existing async handler functions as FastMCP tools.

Usage:
    python -m mcp_server
"""

from __future__ import annotations

import signal
import sys

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
from mcp_server.infrastructure.mcp_client_pool import close_all
from mcp_server.infrastructure.upstream_availability import (
    codebase_upstream_available,
    prd_upstream_available,
)

# ── Server Instance ────────────────────────────────────────────────────────

mcp = FastMCP(
    name="methodology-agent",
    version="1.0.0",
    instructions=(
        "Cortex cognitive profiling system for Claude Code. "
        "Extracts reasoning signatures from session history and pre-loads them at session start. "
        "Call query_methodology at the beginning of every session. "
        "Use remember/recall for persistent thermodynamic memory across sessions."
    ),
)

# ── Tool Registration ──────────────────────────────────────────────────────


def register_all(mcp: FastMCP, *, codebase: bool, prd: bool) -> None:
    """Wire every tool registry onto ``mcp``.

    The 43 standalone tools always register. The 3 upstream-integration tools
    register only when their upstream MCP server is available — ``codebase``
    gates ingest_codebase + change_impact (automatised-pipeline), ``prd`` gates
    ingest_prd (prd-spec-generator). source: MCP Directory decision 2026-06-19.
    """
    tool_registry_core.register(mcp)
    tool_registry_memory.register(mcp)
    tool_registry_manage.register(mcp)
    tool_registry_nav.register(mcp)
    tool_registry_advanced.register(mcp)
    tool_registry_wiki.register(mcp)
    tool_registry_ingest.register(mcp, codebase=codebase, prd=prd)


register_all(
    mcp,
    codebase=codebase_upstream_available(),
    prd=prd_upstream_available(),
)

# ── Lifecycle ──────────────────────────────────────────────────────────────


def _shutdown(sig=None, frame=None) -> None:
    close_all()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
