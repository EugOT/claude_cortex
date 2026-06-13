"""Node-click orchestrator: Cortex + automatised-pipeline as ONE whole.

User direction (2026-06-13): the galaxy loads nothing but names and
positions; clicking a node tells the ORCHESTRATOR to call the MCP
tools — automatised-pipeline (the Rust codebase analysis) for the live
code truth, and Cortex for the data and memories associated with the
node. This module IS that orchestrator: the viz server's
``/api/graph/node`` endpoint delegates here, and every section the
panel shows comes from a real tool call, never from a client-side copy.

Composition root (handlers layer): wires ``infrastructure.ap_bridge``
(AP MCP over stdio) + the ``recall`` handler (Cortex memory retrieval).
Failures degrade per-source: an unreachable AP returns
``{"error": ...}`` in its section while memories still load, and vice
versa — the click never breaks outright.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Bound the per-click recall page. Mirrors the recall tool's own
# default page sizing convention; the panel links into the Knowledge
# view for the full set (defer, never discard).
_MEMORY_PAGE = 5


def _ap_section(record: dict) -> dict[str, Any] | None:
    """Live automatised-pipeline call for code nodes (symbol / file).

    Symbols: ``get_context(graph_path, qualified_name)`` — definition,
    relationships, community — the Rust server's typed answer. Files:
    no qualified name exists, so AP is skipped (the file's symbol list
    already comes from the adjacency index). Returns ``None`` for
    non-code kinds, ``{"error": ...}`` when AP is down.
    """
    kind = record.get("kind") or record.get("type")
    if kind != "symbol":
        return None
    qn = record.get("qualified_name")
    if not qn:
        return {"error": "no qualified_name on record (pre-fix build)"}

    from mcp_server.infrastructure import ap_bridge
    from mcp_server.infrastructure.ap_bridge import resolve_graph_paths

    if not ap_bridge.is_enabled():
        return {"error": "automatised-pipeline disabled"}

    src = _ast_source()
    bridge = src._bridge  # noqa: SLF001 — same pattern as trace impact
    loop_run = src._loop_owner.run  # noqa: SLF001

    # The symbol's project graph: match the record's domain slug against
    # the roster directory names; fall back to trying every graph (the
    # roster is small post-hygiene).
    domain = (record.get("domain") or "").lower()
    paths = resolve_graph_paths()
    ordered = sorted(
        paths,
        key=lambda p: 0 if domain and domain in p.lower() else 1,
    )
    last_err: str | None = None
    for gp in ordered:
        try:
            ctx = loop_run(bridge.get_context(gp, qn))
            if ctx:
                return {"tool": "get_context", "graph": gp, "result": ctx}
        except Exception as exc:  # noqa: BLE001 — degrade per-source
            last_err = f"{type(exc).__name__}: {exc}"
    return {"error": last_err or "symbol not found in any indexed graph"}


_ast_source_singleton = None


def _ast_source():
    global _ast_source_singleton
    if _ast_source_singleton is None:
        from mcp_server.infrastructure.workflow_graph_source_ast import (
            WorkflowGraphASTSource,
        )

        _ast_source_singleton = WorkflowGraphASTSource()
    return _ast_source_singleton


def _memories_section(record: dict) -> dict[str, Any]:
    """Cortex recall for the node — the memories associated with it.

    Query = the node's most specific name (qualified name > path >
    label > id). One bounded recall page; the response keeps totals so
    nothing is silently dropped.
    """
    from mcp_server.handlers.recall import handler as recall_handler

    query = (
        record.get("qualified_name")
        or record.get("path")
        or record.get("label")
        or str(record.get("id") or "")
    )
    if not query:
        return {"memories": [], "query": ""}
    try:
        res = asyncio.run(recall_handler({"query": query, "max_results": _MEMORY_PAGE}))
    except Exception as exc:  # noqa: BLE001 — degrade per-source
        return {"error": f"{type(exc).__name__}: {exc}", "query": query}
    mems = []
    for m in (res or {}).get("memories", [])[:_MEMORY_PAGE]:
        mems.append(
            {
                "id": m.get("id"),
                "content": str(m.get("content") or "")[:280],
                "heat": m.get("heat"),
                "score": m.get("score") or m.get("rerank_score"),
            }
        )
    return {
        "memories": mems,
        "query": query,
        "total": len((res or {}).get("memories", [])),
    }


def inspect_node(record: dict) -> dict[str, Any]:
    """Orchestrate the per-click tool calls for one node record."""
    return {
        "ap": _ap_section(record),
        "cortex": _memories_section(record),
    }
