"""Response shaping for codebase_analyze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.codebase_parser import EXT_TO_LANG


def language_names(source_files: list[Path]) -> list[str]:
    return list({EXT_TO_LANG.get(f.suffix.lower(), "?") for f in source_files})


def dry_run_response(root: Path, source_files: list[Path]) -> dict[str, Any]:
    return {
        "analyzed": False,
        "dry_run": True,
        "directory": str(root),
        "source_files": len(source_files),
        "languages": language_names(source_files),
    }


def success_response(
    root: Path,
    source_files: list[Path],
    counts: tuple[int, int, int, int, int],
    stale: int,
    graph_stats: dict[str, int],
) -> dict[str, Any]:
    new_c, upd_c, unch_c, ents, rels = counts
    return {
        "analyzed": True,
        "directory": str(root),
        "source_files": len(source_files),
        "new": new_c,
        "updated": upd_c,
        "unchanged": unch_c,
        "stale_marked": stale,
        "entities": ents,
        "relationships": rels,
        "graph": graph_stats,
        "languages": language_names(source_files),
    }
