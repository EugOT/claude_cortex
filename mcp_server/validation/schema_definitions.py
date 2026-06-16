"""Schema declarations for MCP tool argument validation."""

from __future__ import annotations

# ADR-0045 R2/R5 (fragility sweep v3.13.0 E3): content envelope tightened
# from 50K to 10K chars after large memory writes triggered unbounded
# extraction/indexing cost.
MEMORY_CONTENT_MAX_CHARS = 10_000
# ADR-0045 R2 (fragility sweep v3.13.0 E4): bounded tag fan-out prevents
# FTS/entity-index blowups from untrusted caller-provided tag arrays.
MEMORY_TAG_MAX_ITEMS = 20
MEMORY_TAG_MAX_CHARS = 80
# Schema v1 compatibility envelope for short routing/label fields. These are
# not content bodies; changing them is an API contract change and should be
# backed by caller telemetry or a migration.
SHORT_LABEL_MAX_CHARS = 200
PATH_FIELD_MAX_CHARS = 500
TIMESTAMP_MAX_CHARS = 64
# Cortex heat is normalized to [0, 1] throughout thermodynamic scoring; see
# docs/papers/thermodynamic-memory-vs-flat-importance.md §4.
NORMALIZED_SCORE_MIN = 0.0
NORMALIZED_SCORE_MAX = 1.0
# Wiki write envelopes preserve the existing authoring API: paths/titles stay
# short, summaries fit a compact page synopsis, and page bodies keep the
# pre-validation storage cap pending wiki corpus telemetry.
WIKI_KIND_MAX_CHARS = 20
WIKI_RELATION_MAX_CHARS = 40
WIKI_SUMMARY_MAX_CHARS = 5_000
WIKI_SECTION_MAX_CHARS = 20_000
WIKI_PAGE_MAX_CHARS = 200_000

# Each property has a type and optional default.
SCHEMAS: dict[str, dict] = {
    "query_methodology": {
        "properties": {
            "cwd": {"type": "string"},
            "project": {"type": "string"},
            "first_message": {"type": "string"},
        },
        "required": [],
    },
    "detect_domain": {
        "properties": {
            "cwd": {"type": "string"},
            "project": {"type": "string"},
            "first_message": {"type": "string"},
        },
        "required": [],
    },
    "rebuild_profiles": {
        "properties": {
            "domain": {"type": "string"},
            "force": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    "list_domains": {
        "properties": {},
        "required": [],
    },
    "record_session_end": {
        "properties": {
            "session_id": {"type": "string"},
            "domain": {"type": "string"},
            "tools_used": {"type": "array"},
            "duration": {"type": "number"},
            "turn_count": {"type": "number"},
            "keywords": {"type": "array"},
            "cwd": {"type": "string"},
            "project": {"type": "string"},
        },
        "required": ["session_id"],
    },
    "get_methodology_graph": {
        "properties": {
            "domain": {"type": "string"},
        },
        "required": [],
    },
    "open_visualization": {
        "properties": {
            "domain": {"type": "string"},
        },
        "required": [],
    },
    "explore_features": {
        "properties": {
            "mode": {"type": "string"},
            "domain": {"type": "string"},
            "compare_domain": {"type": "string"},
        },
        "required": ["mode"],
    },
    "run_pipeline": {
        "properties": {
            "codebase_path": {"type": "string"},
            "task_path": {"type": "string"},
            "context_path": {"type": "string"},
            "github_repo": {"type": "string"},
            "server": {"type": "string", "default": "ai-architect"},
            "max_findings": {"type": "number", "default": 5},
        },
        "required": ["codebase_path", "task_path"],
    },
    "remember": {
        "properties": {
            "content": {"type": "string", "maxLength": MEMORY_CONTENT_MAX_CHARS},
            "tags": {
                "type": "array",
                "maxItems": MEMORY_TAG_MAX_ITEMS,
                "items": {"type": "string", "maxLength": MEMORY_TAG_MAX_CHARS},
            },
            "source": {"type": "string", "maxLength": SHORT_LABEL_MAX_CHARS},
            "domain": {"type": "string", "maxLength": SHORT_LABEL_MAX_CHARS},
            "directory": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "agent_topic": {"type": "string", "maxLength": SHORT_LABEL_MAX_CHARS},
            "importance": {"type": "number"},
            "created_at": {"type": "string", "maxLength": TIMESTAMP_MAX_CHARS},
            "initial_heat": {
                "type": "number",
                "minimum": NORMALIZED_SCORE_MIN,
                "maximum": NORMALIZED_SCORE_MAX,
            },
        },
        "required": ["content"],
    },
    "recall": {
        "properties": {
            "query": {"type": "string", "maxLength": MEMORY_CONTENT_MAX_CHARS},
            "limit": {"type": "number"},
            "domain": {"type": "string", "maxLength": SHORT_LABEL_MAX_CHARS},
            "directory": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "agent_topic": {"type": "string", "maxLength": SHORT_LABEL_MAX_CHARS},
        },
        "required": ["query"],
    },
    "wiki_write": {
        "properties": {
            "path": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "content": {"type": "string", "maxLength": WIKI_PAGE_MAX_CHARS},
            "mode": {"type": "string"},
            "title": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "summary": {"type": "string", "maxLength": WIKI_SUMMARY_MAX_CHARS},
            "body": {"type": "string", "maxLength": WIKI_PAGE_MAX_CHARS},
            "tags": {"type": "array"},
        },
        "required": ["path"],
    },
    "wiki_read": {
        "properties": {
            "path": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
        },
        "required": ["path"],
    },
    "wiki_list": {
        "properties": {
            "kind": {"type": "string", "maxLength": WIKI_KIND_MAX_CHARS},
        },
        "required": [],
    },
    "wiki_link": {
        "properties": {
            "from_path": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "to_path": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "relation": {"type": "string", "maxLength": WIKI_RELATION_MAX_CHARS},
        },
        "required": ["from_path", "to_path", "relation"],
    },
    "wiki_adr": {
        "properties": {
            "title": {"type": "string", "maxLength": PATH_FIELD_MAX_CHARS},
            "context": {"type": "string", "maxLength": WIKI_SECTION_MAX_CHARS},
            "decision": {"type": "string", "maxLength": WIKI_SECTION_MAX_CHARS},
            "consequences": {"type": "string", "maxLength": WIKI_SECTION_MAX_CHARS},
            "status": {"type": "string", "maxLength": WIKI_RELATION_MAX_CHARS},
            "tags": {"type": "array"},
        },
        "required": ["title", "context", "decision", "consequences"],
    },
    "wiki_reindex": {
        "properties": {},
        "required": [],
    },
    "codebase_analyze": {
        "properties": {
            "directory": {"type": "string"},
            "languages": {"type": "array"},
            "max_files": {"type": "number"},
            "max_file_size_kb": {"type": "number"},
            "incremental": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "domain": {"type": "string"},
        },
        "required": [],
    },
}
