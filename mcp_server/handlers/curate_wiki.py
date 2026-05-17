"""Handler: curate_wiki — emit authoring jobs the in-session LLM consumes.

Composition root for the auto-curator (``mcp_server.core.auto_curator``).

Architecture — why this returns jobs instead of authoring directly:

The user's Claude Code session is itself the authoring LLM (Opus 4.7).
Rather than calling an external Anthropic API with a separate key (the
key is the user's session and exposing it via env is fragile), this
handler returns **structured authoring jobs** — clusters of PG memories
paired with the structured prompt the LLM should consume. The in-session
LLM reads the jobs, authors each page in turn, and writes them via
``wiki_write``.

That means the auto-curator's "auto" property comes from two things:

  1. The clustering and prompt-construction work happens without a human
     deciding what to document — ``curate_wiki`` fetches recent
     high-heat clusters, derives topics, and constructs prompts that
     embed all the wiki conventions.

  2. The trigger is automatic — ``consolidate`` runs the same job-
     enqueueing logic on its periodic cycle; SessionStart surfaces
     pending curations to the in-session LLM. The user never asks for
     a specific page; the system notices what deserves documentation
     and proposes it.

The user directive this satisfies:
  > "ALL ACTIONS SHOULD DOCUMENTED BY OPUS 4.7, IT'S NOT POSSIBLE THE
  > LLM IS NOT ABLE TO PRODUCE A DOCUMENTATION FROM AN ACCESS."
  > "The documentation you created now, should be auto created and auto
  > curated."
  > "the anthropic key should be using the user session"
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.core.auto_curator import (
    MAX_MEMORIES_PER_PROMPT,
    MIN_AVG_HEAT_FOR_PAGE,
    MIN_MEMORIES_PER_CLUSTER,
    build_clusters,
    build_jobs,
)
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_store import MemoryStore


schema = {
    "title": "Curate wiki",
    "annotations": READ_ONLY,
    "description": (
        "Auto-curator: returns structured authoring jobs the in-session "
        "LLM (Opus 4.7) consumes to author curated wiki pages from PG "
        "memory clusters. Each job carries one cluster's memories, the "
        "suggested wiki path, a list of existing related pages for "
        "cross-linking, and a complete structured prompt that encodes "
        "the wiki documentation conventions (frontmatter, lead, "
        "diagrams, 'why this not the alternatives', 'what can go "
        "wrong', 'see also', primary sources). The conversational LLM "
        "reads each job, authors the page in Markdown, and writes it "
        "via `wiki_write`. No external Anthropic API key required — "
        "the user's existing Claude Code session is the authoring LLM. "
        "Distinct from `wiki_write` (the writer; this is the planner), "
        "`narrative` (one summary; this is N pages), and `consolidate` "
        "(memory maintenance; this is documentation production). "
        "Read-only with respect to PG and wiki. Latency ~300ms for "
        "k=5 jobs. Returns {jobs: [{cluster, prompt, suggested_path, "
        "related_pages}], total_clusters_eligible, instructions}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Restrict curation to a single domain. Omit to "
                    "curate across all domains (sorted by cluster "
                    "value)."
                ),
                "examples": ["cortex", "agentic-ai"],
            },
            "limit": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "maximum": 20,
                "description": (
                    "Maximum number of authoring jobs to return. "
                    "Higher = more pages to author per invocation; "
                    "lower = focus on the highest-value clusters."
                ),
            },
            "min_memories": {
                "type": "integer",
                "default": MIN_MEMORIES_PER_CLUSTER,
                "description": (
                    "Minimum memories per cluster to earn a page. "
                    "Below this, a topic doesn't have enough signal."
                ),
            },
            "min_avg_heat": {
                "type": "number",
                "default": MIN_AVG_HEAT_FOR_PAGE,
                "description": (
                    "Minimum average effective_heat of cluster "
                    "memories. Cold clusters yield stale pages."
                ),
            },
            "recent_only": {
                "type": "boolean",
                "default": True,
                "description": (
                    "If true, only consider recently-accessed memories. "
                    "If false, scan the full corpus (slower)."
                ),
            },
            "memory_pool_size": {
                "type": "integer",
                "default": 500,
                "description": (
                    "Number of memories to draw from before clustering. "
                    "Higher = better topic coverage, more compute."
                ),
            },
        },
    },
}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _scan_existing_pages(wiki_root: Path) -> dict[str, list[str]]:
    """Build a topic→[paths] index of existing wiki pages.

    The auto-curator uses this to suggest cross-links via ``[[wiki/path]]``
    notation in the authoring prompt. Topics are derived from the page
    path's slug (last component, minus extension).
    """
    index: dict[str, list[str]] = {}
    if not wiki_root.is_dir():
        return index
    for md_path in wiki_root.rglob("*.md"):
        rel = md_path.relative_to(wiki_root)
        parts = rel.parts
        if not parts or parts[0].startswith((".", "_")):
            continue
        slug = md_path.stem
        # Drop common ID prefixes like "305772-" so the topic is the
        # human-readable part of the slug
        slug = re.sub(r"^\d+-", "", slug)
        # Normalise "decision-" / "lesson-" / "convention-" prefixes
        slug = re.sub(r"^(decision|lesson|convention|spec|reference)-", "", slug)
        # Strip trailing common words ("md")
        slug = slug.replace("-md", "")
        # Use the slug itself as the topic key (lowercased)
        topic = slug.lower()
        path_str = str(rel).replace(".md", "")
        index.setdefault(topic, []).append(path_str)
    return index


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build authoring jobs from PG memory clusters."""
    args = args or {}
    domain = args.get("domain") or None
    limit = int(args.get("limit") or 3)
    min_memories = int(args.get("min_memories") or MIN_MEMORIES_PER_CLUSTER)
    min_avg_heat = float(args.get("min_avg_heat") or MIN_AVG_HEAT_FOR_PAGE)
    recent_only = bool(args.get("recent_only", True))
    memory_pool_size = int(args.get("memory_pool_size") or 500)

    store = MemoryStore()
    # Draw a memory pool. Recently-accessed memories are higher-signal
    # candidates because they reflect what the user actively works on.
    if recent_only:
        memories = store.get_recently_accessed_memories(limit=memory_pool_size)
        if len(memories) < min_memories * 2:
            # Fall back to the recent-by-creation pool when access is
            # thin (e.g. fresh DB).
            memories = store.get_recent_memories(limit=memory_pool_size)
    else:
        memories = store.get_recent_memories(limit=memory_pool_size)

    if not memories:
        return {
            "jobs": [],
            "total_clusters_eligible": 0,
            "instructions": "No memories available to curate. Use `remember` to seed.",
            "memory_pool_size": 0,
        }

    clusters = build_clusters(
        memories,
        domain=domain,
        min_memories=min_memories,
        min_avg_heat=min_avg_heat,
        wiki_root=str(WIKI_ROOT),
        skip_recently_authored=True,
    )

    existing_pages = _scan_existing_pages(Path(WIKI_ROOT))
    jobs = build_jobs(clusters, existing_pages, today=_today())

    selected = jobs[:limit]
    payload = [_serialise_job(j) for j in selected]

    return {
        "jobs": payload,
        "total_clusters_eligible": len(clusters),
        "returned": len(payload),
        "memory_pool_size": len(memories),
        "domain_filter": domain or "(all)",
        "instructions": _instructions_for_llm(len(payload), len(clusters)),
    }


def _serialise_job(job: Any) -> dict[str, Any]:
    """Flatten a CurationJob for MCP wire transport."""
    c = job.cluster
    return {
        "suggested_path": c.suggested_path,
        "suggested_kind": c.suggested_kind,
        "topic": c.topic,
        "domain": c.domain,
        "memory_count": len(c.memory_ids),
        "memory_ids": c.memory_ids,
        "top_entities": c.entities[:8],
        "avg_heat": round(c.avg_heat, 3),
        "earliest_memory_at": c.earliest_at,
        "latest_memory_at": c.latest_at,
        "related_pages": job.related_pages,
        "prompt": job.prompt,
    }


def _instructions_for_llm(n_jobs: int, n_eligible: int) -> str:
    """The recipe the conversational Opus 4.7 follows when consuming jobs."""
    if n_jobs == 0:
        return (
            f"No curation jobs returned. {n_eligible} clusters were "
            "eligible. If you expected jobs, relax `min_memories` or "
            "`min_avg_heat`, or pass `recent_only=false`."
        )
    return (
        f"Auto-curator returned {n_jobs} job(s) (of {n_eligible} eligible "
        "clusters). For each job in order:\n"
        "  1. Read `prompt` — it contains the cluster's memories and the "
        "authoring conventions.\n"
        "  2. Author the page in Markdown following the conventions "
        "(frontmatter → lead → sections with diagrams → 'why this not "
        "alternatives' → 'what can go wrong' → 'see also' → primary "
        "sources).\n"
        "  3. Write the page via `wiki_write(path=<job.suggested_path>, "
        "content=<your authored Markdown>, tags=['wiki', 'llm-authored', "
        "<topic>, <domain>])`.\n"
        "  4. Call `curate_wiki` again to fetch the next batch when "
        "this batch is done.\n"
        "Do not skip the structure — the conventions are how readers "
        "find what they need across pages. Do not dump raw memory "
        "content; synthesise. Each page should be 8-15 KB of substantive "
        "authored prose, not a template."
    )
