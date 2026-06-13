"""Tests for codebase_communities — Leiden/Louvain, centrality, god nodes."""

from __future__ import annotations

import pytest

from mcp_server.core.codebase_communities import (
    compute_centrality,
    detect_communities,
    detect_god_nodes,
)

nx = pytest.importorskip("networkx")


# ── Community detection ─────────────────────────────────────────────────────


def test_two_clusters_separate() -> None:
    """Two dense triangles joined by one edge split into two communities."""
    file_edges = [
        ("a.py", "b.py"),
        ("b.py", "c.py"),
        ("a.py", "c.py"),
        ("d.py", "e.py"),
        ("e.py", "f.py"),
        ("d.py", "f.py"),
        ("c.py", "d.py"),
    ]
    communities = detect_communities(file_edges, [])
    assert communities["a.py"] == communities["b.py"] == communities["c.py"]
    assert communities["d.py"] == communities["e.py"] == communities["f.py"]
    assert communities["a.py"] != communities["d.py"]


def test_self_loop_single_node() -> None:
    communities = detect_communities([("a.py", "a.py")], [])
    assert "a.py" in communities


def test_empty_edges() -> None:
    assert detect_communities([], []) == {}


def test_deterministic() -> None:
    """Same input → same partition (seeded)."""
    edges = [("a.py", "b.py"), ("c.py", "d.py"), ("b.py", "c.py")]
    assert detect_communities(edges, []) == detect_communities(edges, [])


def test_leiden_used_when_available() -> None:
    """When leidenalg is installed, the Leiden path produces a partition."""
    pytest.importorskip("leidenalg")
    pytest.importorskip("igraph")
    edges = [("a", "b"), ("a", "c"), ("b", "c"), ("d", "e"), ("c", "d")]
    communities = detect_communities(edges, [])
    assert len(communities) == 5
    assert communities["a"] == communities["b"]


# ── Centrality ──────────────────────────────────────────────────────────────


def test_centrality_keys_and_range() -> None:
    edges = [("hub.py", "a.py"), ("hub.py", "b.py"), ("hub.py", "c.py")]
    centrality = compute_centrality(edges, [])
    assert set(centrality["hub.py"]) == {"degree", "betweenness", "pagerank"}
    for scores in centrality.values():
        for v in scores.values():
            assert 0.0 <= v <= 1.0


def test_hub_has_highest_degree() -> None:
    edges = [("hub.py", f"leaf{i}.py") for i in range(6)]
    centrality = compute_centrality(edges, [])
    hub = centrality["hub.py"]["degree"]
    assert all(hub >= centrality[n]["degree"] for n in centrality)


def test_centrality_empty() -> None:
    assert compute_centrality([], []) == {}


# ── God nodes ───────────────────────────────────────────────────────────────


def test_god_node_detected() -> None:
    """A star hub is a degree-centrality outlier → flagged as a god node."""
    edges = [("god.py", f"leaf{i}.py") for i in range(12)]
    gods = detect_god_nodes(compute_centrality(edges, []))
    assert gods == ["god.py"]


def test_no_god_node_in_uniform_graph() -> None:
    """A ring graph has uniform degree → no outlier, no god node."""
    nodes = [f"n{i}.py" for i in range(8)]
    edges = [(nodes[i], nodes[(i + 1) % 8]) for i in range(8)]
    assert detect_god_nodes(compute_centrality(edges, [])) == []


def test_god_node_empty() -> None:
    assert detect_god_nodes({}) == []
