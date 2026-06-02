"""Shared helpers for ingest_codebase and ingest_prd handlers.

Two concerns live here:

1. Graph-path memoisation — after a codebase analysis, the returned
   graph_path is stored as a protected Cortex memory tagged
   ``_code_graph:<project-id>`` so subsequent ingest runs can reuse
   the same graph without re-indexing.

2. Safe MCP calls — wraps mcp_client_pool.get_client + call with a
   uniform error shape so ingest handlers don't each re-derive the
   try/except boilerplate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.mcp_client_pool import get_client

CODE_GRAPH_TAG_PREFIX = "_code_graph:"


def project_key(project_path: str) -> str:
    """Stable project key = last path segment + short hash of full path."""
    p = Path(project_path).expanduser().resolve()
    digest = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:8]
    return f"{p.name}-{digest}"


def code_graph_tag(project_path: str) -> str:
    """Canonical tag used to memoise a code graph path for a project."""
    return f"{CODE_GRAPH_TAG_PREFIX}{project_key(project_path)}"


def graph_path_is_materialised(graph_path: str | None) -> bool:
    """True when ``graph_path`` points at a graph that still exists on disk.

    AP writes ``<output_dir>/graph`` as a LadybugDB directory; pre-3.14
    builds wrote a single file at the same slot. Either form counts as
    valid only when **non-empty** — an existing-but-empty directory is a
    half-built or wiped graph, which must read as a cache miss so the
    caller re-analyses rather than silently projecting zero symbols.

    source: ingest staleness bug Jun-2026 — a memo outlived its graph
    (the graph directory was deleted) and ``find_cached_graph`` handed the
    dead path straight back to ``ensure_graph``, which then projected an
    empty graph. A memo must never outlive the artefact it points at
    (Dijkstra audit: the pointer is not the thing).
    """
    if not graph_path:
        return False
    try:
        p = Path(graph_path).expanduser()
        if not p.exists():
            return False
        if p.is_dir():
            return any(p.iterdir())
        return p.stat().st_size > 0
    except OSError:
        return False


def _memo_tags(mem: dict) -> list:
    """Tags of a memory row as a list (rows may store JSON-encoded tags)."""
    raw = mem.get("tags", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return raw if isinstance(raw, list) else []


def _memo_recency_key(mem: dict) -> str:
    """Sortable recency key for a memo row (most-recent sorts highest).

    Prefers ``created_at`` (when the path was memoised); falls back to
    ``heat_base_set_at`` then ``last_accessed``. Datetimes are
    ISO-normalised; a missing value sorts oldest. ISO-8601 strings sort
    lexicographically in chronological order, so plain string comparison
    is correct here.
    """
    for field in ("created_at", "heat_base_set_at", "last_accessed"):
        val = mem.get(field)
        if val is None or val == "":
            continue
        iso = getattr(val, "isoformat", None)
        return iso() if callable(iso) else str(val)
    return ""


def find_cached_graph(store, project_path: str) -> str | None:
    """Return the cached graph_path for a project, or None.

    Returns the path from the MOST-RECENT memo tagged with the project's
    code-graph tag whose graph **still exists on disk**. A memo whose
    graph was deleted (path missing or empty) is skipped, never returned
    — this is the self-heal: a stale memo can no longer make the caller
    project an empty graph. When no live graph is found, returns None so
    the caller re-analyses and re-memoises.

    source: ingest staleness bug Jun-2026 (Dijkstra audit). Previously
    this returned the first tag match unconditionally, with no existence
    check and no recency ordering.
    """
    tag = code_graph_tag(project_path)
    try:
        mems = store.get_all_memories_for_decay()
    except Exception:
        return None

    candidates: list[tuple[str, str]] = []  # (recency_key, graph_path)
    for mem in mems:
        if tag not in _memo_tags(mem):
            continue
        content = mem.get("content") or ""
        if not content.startswith("graph_path="):
            continue
        path = content[len("graph_path=") :].strip()
        if path:
            candidates.append((_memo_recency_key(mem), path))

    # Most-recent first; return the first whose graph is materialised.
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _, path in candidates:
        if graph_path_is_materialised(path):
            return path
    return None


def memoise_graph_path(store, project_path: str, graph_path: str) -> int | None:
    """Persist the graph path as a protected memory for future lookups.

    Uses raw insert_memory (not the predictive-coding gate) so ingestion
    state is always recorded, even when low-surprise.
    """
    tag = code_graph_tag(project_path)
    record = {
        "content": f"graph_path={graph_path}",
        "tags": [tag, "_ingest", "code-graph"],
        "source": "ingest_codebase",
        "domain": "cortex-ingest",
        "directory_context": str(Path(project_path).expanduser().resolve()),
        "is_protected": True,
        "importance": 1.0,
        "heat": 1.0,
    }
    try:
        return store.insert_memory(record)
    except Exception:
        return None


async def call_upstream(
    server_name: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Invoke a tool on an upstream MCP server; return parsed result.

    Raises McpConnectionError on connection/transport failure. Returns
    the tool result as a plain dict when the server answers successfully.
    """
    client = await get_client(server_name)
    response = await client.call(tool_name, args)
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        try:
            return json.loads(response)
        except (ValueError, TypeError):
            return {"text": response}
    return {"value": response}


def normalise_mcp_payload(payload: Any) -> Any:
    """MCP call() sometimes returns a dict with a 'content' array.

    The pipeline's tools emit ``{"content": [{"type": "text", "text": "{...}"}]}``;
    callers want the inner JSON. Other servers answer with a plain dict.
    This helper collapses both shapes to the underlying object.
    """
    if isinstance(payload, dict) and "content" in payload:
        content = payload["content"]
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                text = first.get("text", "")
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return {"text": text}
    return payload
