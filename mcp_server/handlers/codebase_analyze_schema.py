"""Tool schema for the codebase_analyze handler."""

from __future__ import annotations

from mcp_server.handlers._tool_meta import NON_IDEMPOTENT_WRITE

schema = {
    "title": "Codebase analyze",
    "annotations": NON_IDEMPOTENT_WRITE,
    "description": (
        "Walk a codebase and store its structure as memories using tree-"
        "sitter AST parsing (with regex fallback for unsupported "
        "languages). One memory per file, with symbols as entities and "
        "imports as relationships; then cross-file symbol resolution, "
        "call-graph extraction, and community detection over the call "
        "graph. Incremental - only re-processes files whose content hash "
        "changed since last run (tracked via HASH_TAG_PREFIX tags). Use "
        "this on first onboarding to a serious codebase, or after a major "
        "refactor that invalidates symbol assumptions. Distinct from "
        "`seed_project` (5-stage shallow structural sweep, no AST), "
        "`backfill_memories` (Claude Code conversations, not source "
        "files), `wiki_seed_codebase` (seeds wiki pages from .md docs), "
        "and `ingest_codebase` (downstream PRD-generator consumer). "
        "Mutates memories + entities + relationships tables. Latency "
        "varies (~10s-10min depending on tree size). Returns "
        "{files_analyzed, files_skipped, memories_written, entities_"
        "created, relationships_created}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory of the codebase to analyze. Defaults to the current working directory.",
                "examples": ["/Users/alice/code/cortex"],
            },
            "languages": {
                "type": "array",
                "description": (
                    "Restrict analysis to specific languages by tree-sitter "
                    "grammar name. Omit to auto-detect from file extensions."
                ),
                "items": {
                    "type": "string",
                    "enum": [
                        "python",
                        "javascript",
                        "typescript",
                        "rust",
                        "go",
                        "java",
                        "swift",
                        "c",
                        "cpp",
                        "ruby",
                    ],
                },
                "default": [],
                "examples": [["python"], ["typescript", "javascript"]],
            },
            "max_files": {
                "type": "integer",
                "description": "Maximum number of files to process per call. Set to 0 (default) for no limit - process every matching file. Use a positive cap only to bound runaway analysis on extremely large monorepos.",
                "default": 0,
                "minimum": 0,
                "examples": [0, 500, 5000],
            },
            "max_file_size_kb": {
                "type": "integer",
                "description": "Skip files larger than this many kilobytes (typically generated files or binary blobs).",
                "default": 100,
                "minimum": 1,
                "maximum": 4096,
                "examples": [100, 256],
            },
            "incremental": {
                "type": "boolean",
                "description": "Only re-process files whose content hash changed since the last analysis. Disable for a clean rescan.",
                "default": True,
            },
            "dry_run": {
                "type": "boolean",
                "description": "Report what would be analyzed and stored without writing any memories.",
                "default": False,
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to tag analysis memories with. Auto-detected from directory if omitted.",
                "examples": ["cortex", "auth-service"],
            },
        },
    },
}
