"""Cold-start + live-stream contract for the streaming galaxy build.

These tests pin the behaviour that replaced the deleted binary-snapshot
("Solution 1") delivery path. The live SSE stream (/api/graph/events,
fed by ``graph_event_stream``) is the only graph delivery mechanism, so:

* ``ensure_build_started`` must kick the background build whenever the
  in-process cache is empty — there is no on-disk snapshot that can
  suppress the build any more (the old ``_complete_snapshot_counts``
  short-circuit made a cold process sit blank forever).
* ``get_build_progress`` must report the real progress state and never
  fabricate ``full_ready=True`` from a file on disk.
* The build must emit every merged delta onto the SSE event stream and
  close the stream exactly once, at the true end of the build — closing
  it at baseline made subscribers receive ``done`` and disconnect before
  a single L6 symbol streamed (observed 2026-06-12).
* Emission is added-only: a node merged twice (skeleton + full baseline)
  appears in exactly one stream event, so the replay buffer carries no
  duplicates.
"""

import time
from unittest.mock import patch

from mcp_server.server import graph_event_stream
from mcp_server.server import http_standalone_graph as graph


def _reset_module_state():
    """Return module globals to a fresh-process state."""
    graph._graph_cache = None
    with graph._build_progress_lock:
        graph._build_progress.update(
            {
                "phase": "idle",
                "phase_seq": 0,
                "pct": 0.0,
                "baseline_ready": False,
                "full_ready": False,
                "node_count": 0,
                "edge_count": 0,
                "started_at": 0.0,
            }
        )


def test_ensure_build_started_kicks_when_cache_empty():
    """Empty in-process cache (cold start) → the build is kicked.

    No on-disk snapshot can suppress it any more.
    """
    _reset_module_state()
    sentinel = object()
    with patch.object(graph, "_kick_background_build") as kick:
        graph.ensure_build_started(sentinel)
    kick.assert_called_once_with(sentinel, None)


def test_ensure_build_started_skips_when_cache_has_nodes():
    """A populated cache means a build already ran — do not re-kick."""
    _reset_module_state()
    graph._graph_cache = {"data": {"nodes": [{"id": "domain:x"}], "edges": []}}
    with patch.object(graph, "_kick_background_build") as kick:
        graph.ensure_build_started(object())
    kick.assert_not_called()


def test_ensure_build_started_skips_when_build_running():
    """The build lock being held means a build is in flight — do not
    spawn a second one."""
    _reset_module_state()
    graph._graph_build_lock.acquire(blocking=False)
    try:
        with patch.object(graph, "_kick_background_build") as kick:
            graph.ensure_build_started(object())
        kick.assert_not_called()
    finally:
        graph._graph_build_lock.release()


def test_get_build_progress_does_not_fabricate_readiness():
    """A cold process with no build run reports idle / not-ready — the
    deleted snapshot short-circuit used to flip full_ready=True here."""
    _reset_module_state()
    snap = graph.get_build_progress()
    assert snap["baseline_ready"] is False
    assert snap["full_ready"] is False
    assert snap["phase"] == "idle"


def test_get_build_progress_reports_real_state():
    """Progress reflects the live ``_build_progress`` dict, not disk."""
    _reset_module_state()
    graph._set_progress(phase="baseline_ready", baseline_ready=True, pct=0.3)
    snap = graph.get_build_progress()
    assert snap["baseline_ready"] is True
    assert snap["phase"] == "baseline_ready"
    assert snap["pct"] == 0.3
    _reset_module_state()


# ── Live-stream contract ────────────────────────────────────────────────


_FAKE_GRAPH = {
    "nodes": [
        {"id": "domain:alpha", "kind": "domain", "label": "alpha"},
        {"id": "file:a.py", "kind": "file", "label": "a.py", "path": "a.py"},
    ],
    "edges": [
        {"source": "file:a.py", "target": "domain:alpha", "kind": "in_domain"},
    ],
    "meta": {},
}


def _run_fake_build():
    """Run _kick_background_build with the heavy sources mocked out and
    wait for it to finish. AP is disabled, so the build ends right after
    the baseline (the early-return path) — the stream must still close.
    """

    def fake_build(store, **kwargs):
        return {
            "nodes": [dict(n) for n in _FAKE_GRAPH["nodes"]],
            "edges": [dict(e) for e in _FAKE_GRAPH["edges"]],
            "meta": {},
        }

    with (
        patch(
            "mcp_server.handlers.workflow_graph.build_workflow_graph",
            side_effect=fake_build,
        ),
        patch(
            "mcp_server.infrastructure.ap_bridge.is_enabled",
            return_value=False,
        ),
        patch(
            "mcp_server.infrastructure.ap_bridge.resolve_graph_paths",
            return_value=[],
        ),
        patch(
            "mcp_server.core.layout_engine.layout",
            return_value=[],
        ),
    ):
        graph._kick_background_build(None, None)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            snap = graph.get_build_progress()
            if snap.get("full_ready") or snap.get("phase") == "error":
                break
            time.sleep(0.02)
        # The finally block (lock release + stream close) runs after the
        # last progress update — give it a moment.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not graph._graph_build_lock.locked():
                break
            time.sleep(0.01)


def test_build_emits_to_stream_and_closes_once_at_end():
    """Every merged delta reaches the SSE stream; the stream is closed
    exactly at end-of-build so a subscriber drains everything and then
    receives end-of-stream (the ``done`` frame at the HTTP layer)."""
    _reset_module_state()
    _run_fake_build()

    snap = graph.get_build_progress()
    assert snap["full_ready"] is True, f"build did not finish: {snap}"

    stream = graph_event_stream.get_stream()
    stats = stream.stats()
    assert stats["closed"] is True, "stream must be closed at end-of-build"
    assert stats["count"] > 0, "build emitted nothing onto the stream"

    # A late subscriber replays the full buffer and exits cleanly
    # (closed + drained) — this is the warm-cache delivery path.
    events = list(stream.subscribe(since=0, timeout=0.5))
    assert len(events) == stats["count"]

    # Slim wire contract (graph_event_stream.js decoder counterpart):
    # node = [id, kind, x, y] and the stream carries NO EDGES AT ALL —
    # the planetarium renders dots from id+position alone; neighbors,
    # labels and details are on-demand queries (/api/graph/node, MCP
    # tools). User direction 2026-06-12.
    streamed_nodes = [n for _, ev in events for n in ev.get("nodes", [])]
    streamed_edges = [e for _, ev in events for e in ev.get("edges", [])]
    assert all(isinstance(n, list) and len(n) == 4 for n in streamed_nodes)
    assert streamed_edges == [], "edges must NEVER ride the stream"
    streamed_node_ids = [n[0] for n in streamed_nodes]
    kinds = {n[0]: n[1] for n in streamed_nodes}
    assert kinds.get("domain:alpha") == "domain"
    assert kinds.get("file:a.py") == "file"

    # Added-only emission: the same node is never streamed twice even
    # though skeleton and full baseline both returned it.
    assert len(streamed_node_ids) == len(set(streamed_node_ids))


def test_build_populates_cache_incrementally():
    """The incremental _merge keeps the cumulative cache and the kind
    tallies correct (they are no longer recomputed from the whole cache
    per batch)."""
    _reset_module_state()
    _run_fake_build()

    data = graph._graph_cache["data"]
    ids = {n["id"] for n in data["nodes"]}
    assert ids == {"domain:alpha", "file:a.py"}
    assert len(data["nodes"]) == 2, "duplicate merge must not duplicate nodes"
    assert data["meta"]["domain_count"] == 1
    assert data["meta"]["node_count"] == 2
    assert data["meta"]["edge_count"] == 1
    # Hub-id map is maintained incrementally for the discussions builder.
    assert graph._cached_domain_hub_ids.get("alpha") == "domain:alpha"


def test_node_index_serves_every_kind():
    """get_node_record resolves any merged node id — the /api/graph/node
    fallback that makes non-PG kinds (symbol, file, domain, …)
    browsable in the detail panel."""
    _reset_module_state()
    _run_fake_build()

    rec = graph.get_node_record("domain:alpha")
    assert rec is not None and rec["kind"] == "domain"
    rec = graph.get_node_record("file:a.py")
    assert rec is not None and rec["path"] == "a.py"
    assert graph.get_node_record("symbol:does-not-exist") is None


def test_graph_slice_pages_are_complete():
    """/api/graph/slice contract: bounded pages whose union equals the
    full cache — defer, never discard."""
    _reset_module_state()
    _run_fake_build()

    head = graph.get_graph_slice(offset=0, limit=1)
    assert head["node_total"] == 2
    assert head["done"] is False
    nodes = list(head["nodes"])
    edges = list(head["edges"])
    offset = 1
    while True:
        page = graph.get_graph_slice(offset=offset, limit=1)
        nodes.extend(page["nodes"])
        edges.extend(page["edges"])
        if page["done"]:
            break
        offset += 1
    assert {n["id"] for n in nodes} == {"domain:alpha", "file:a.py"}
    assert len(edges) == head["edge_total"] == 1
    # Slice pages carry FULL records (the wire is slim; the slice is
    # the fidelity path for the MCP handler).
    assert all(isinstance(n, dict) for n in nodes)


def test_place_around_is_deterministic_and_bounded():
    """Symbol placement contract: same key → same position; distance
    from the anchor stays inside the derived 0.05–0.25 world band
    (renderer ratio derivation in the _place_around docstring)."""
    a = graph._place_around(0.5, -0.25, "symbol:abc123")
    b = graph._place_around(0.5, -0.25, "symbol:abc123")
    assert a == b, "placement must be deterministic per id"
    dx, dy = a[0] - 0.5, a[1] + 0.25
    dist = (dx * dx + dy * dy) ** 0.5
    assert 0.04 <= dist <= 0.26, f"distance {dist} outside derived band"
    c = graph._place_around(0.5, -0.25, "symbol:other")
    assert c != a, "different ids spread to different positions"


def test_node_neighbors_served_on_demand():
    """The detail panel's relational data comes from the server's
    adjacency index — one on-demand call, paged, complete — never from
    a client-side join over the full edge copy."""
    _reset_module_state()
    _run_fake_build()

    nb = graph.get_node_neighbors("file:a.py")
    assert nb["total"] == 1
    row = nb["neighbors"][0]
    assert row[0] == "domain:alpha"  # other_id
    assert row[1] == "domain"  # other_kind
    assert row[3] == "in_domain"  # edge_kind
    assert row[4] == "out"  # file -> domain direction
    assert nb["next_offset"] is None

    # Pagination contract on the reverse direction.
    nb2 = graph.get_node_neighbors("domain:alpha", offset=0, limit=1)
    assert nb2["total"] == 1 and nb2["neighbors"][0][4] == "in"
    assert graph.get_node_neighbors("symbol:none")["total"] == 0
