"""Graph-analysis phase for codebase_analyze."""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_store import MemoryStore


def run_graph_analysis(
    analyses: list[Any],
    file_contents: dict[str, str],
    store: MemoryStore,
    domain: str,
) -> dict[str, int]:
    """Run cross-file resolution, type references, and communities."""
    from mcp_server.core.codebase_graph import (
        detect_communities,
        extract_inheritance,
        resolve_all_imports,
    )
    from mcp_server.core.codebase_type_resolver import resolve_type_references
    from mcp_server.handlers.codebase_analyze_helpers import (
        persist_community_tags,
        persist_file_edge,
        persist_inheritance_edge,
    )

    import_edges = resolve_all_imports(analyses)
    type_ref_edges = resolve_type_references(analyses, file_contents)
    all_file_edges = list(set(import_edges + type_ref_edges))
    inherit_edges = extract_inheritance(analyses)
    communities = detect_communities(all_file_edges, [])

    file_rels = persist_file_edge(store, all_file_edges, domain)
    inherit_rels = persist_inheritance_edge(store, inherit_edges, domain)
    persist_community_tags(store, communities)

    return {
        "import_edges": len(import_edges),
        "type_ref_edges": len(type_ref_edges),
        "total_file_edges": len(all_file_edges),
        "inheritance_edges": len(inherit_edges),
        "communities": len(set(communities.values())) if communities else 0,
        "file_edges_stored": file_rels,
        "inherit_edges_stored": inherit_rels,
    }
