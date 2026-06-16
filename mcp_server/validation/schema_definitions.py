"""Schema declarations for MCP tool argument validation."""

from __future__ import annotations

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
            # ADR-0045 R2/R5 (fragility sweep v3.13.0 E3):
            # content maxLength tightened from 50_000 -> 10_000 chars.
            # Taleb audit: a 100 KB content blob triggered ~100K fallback
            # regex scans in entity extraction plus OOM on the knowledge
            # graph path. 10 K is the bounded envelope; callers submitting
            # larger content get a ValidationError and must split upstream.
            "content": {"type": "string", "maxLength": 10000},
            # ADR-0045 R2 (fragility sweep v3.13.0 E4):
            # Bounded tags envelope: at most 20 tags, each <= 80 chars.
            # Prevents a caller from submitting a 10K-element tag list
            # (each tag becomes a tsvector lexeme, an FTS dictionary
            # entry, and a row in memory_entities) which would blow up
            # indexing cost without bounded benefit.
            "tags": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "maxLength": 80},
            },
            "source": {"type": "string", "maxLength": 200},
            "domain": {"type": "string", "maxLength": 200},
            "directory": {"type": "string", "maxLength": 500},
            "agent_topic": {"type": "string", "maxLength": 200},
            "importance": {"type": "number"},
            "created_at": {"type": "string", "maxLength": 64},
            "initial_heat": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["content"],
    },
    "recall": {
        "properties": {
            "query": {"type": "string", "maxLength": 10000},
            "limit": {"type": "number"},
            "domain": {"type": "string", "maxLength": 200},
            "directory": {"type": "string", "maxLength": 500},
            "agent_topic": {"type": "string", "maxLength": 200},
        },
        "required": ["query"],
    },
    "wiki_write": {
        "properties": {
            "path": {"type": "string", "maxLength": 500},
            "content": {"type": "string", "maxLength": 200000},
            "mode": {"type": "string"},
            "title": {"type": "string", "maxLength": 500},
            "summary": {"type": "string", "maxLength": 5000},
            "body": {"type": "string", "maxLength": 200000},
            "tags": {"type": "array"},
        },
        "required": ["path"],
    },
    "wiki_read": {
        "properties": {
            "path": {"type": "string", "maxLength": 500},
        },
        "required": ["path"],
    },
    "wiki_list": {
        "properties": {
            "kind": {"type": "string", "maxLength": 20},
        },
        "required": [],
    },
    "wiki_link": {
        "properties": {
            "from_path": {"type": "string", "maxLength": 500},
            "to_path": {"type": "string", "maxLength": 500},
            "relation": {"type": "string", "maxLength": 40},
        },
        "required": ["from_path", "to_path", "relation"],
    },
    "wiki_adr": {
        "properties": {
            "title": {"type": "string", "maxLength": 500},
            "context": {"type": "string", "maxLength": 20000},
            "decision": {"type": "string", "maxLength": 20000},
            "consequences": {"type": "string", "maxLength": 20000},
            "status": {"type": "string", "maxLength": 40},
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
