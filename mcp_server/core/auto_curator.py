"""Auto-curator — turn PG memory clusters into curated wiki pages.

This module is the systemic answer to "ALL ACTIONS SHOULD BE DOCUMENTED
BY OPUS 4.7" (user directive 2026-05-17). Manual authoring doesn't
scale; periodic mechanical extraction produces empty templates. The
auto-curator sits in between:

  1. Cluster recent PG memories into topic groups (entity co-occurrence +
     heat + domain).
  2. For each cluster that earns a wiki page (≥ N memories, ≥ heat
     threshold, no existing fresh page), construct a structured
     **authoring prompt** that encodes the wiki-page conventions
     (frontmatter, lead, sections with diagrams, "why this not the
     alternatives", "what can go wrong", "see also", primary sources).
  3. Return the prompts as "curation jobs". A downstream LLM (the
     conversational Opus 4.7 via the ``curate_wiki`` MCP tool, or a
     direct Anthropic API call when ``ANTHROPIC_API_KEY`` is set)
     authors the page and writes it via ``wiki_write``.

Pure business logic — no I/O. The handler composes this with the memory
store and the wiki writer.

References (the user-quoted directives this module exists to satisfy):
  * "ALL ACTIONS SHOULD DOCUMENTED BY OPUS 4.7, IT'S NOT POSSIBLE THE
    LLM IS NOT ABLE TO PRODUCE A DOCUMENTATION FROM AN ACCESS."
  * "If I open the wiki I should be able to parse the documentation and
    understand in a clear way how the whole codebase work, what it does,
    and how it was built."
  * "The documentation you created now, should be auto created and auto
    curated."
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

# 2026-05-17: thresholds tuned to mirror the cluster-quality bar of the
# hand-authored pages from this session. Below these, a cluster doesn't
# carry enough signal to author a useful page.
MIN_MEMORIES_PER_CLUSTER = 4
MIN_AVG_HEAT_FOR_PAGE = 0.3
MIN_ENTITY_FREQ_FOR_TOPIC = 3
MAX_MEMORIES_PER_PROMPT = 25  # cap prompt size; cross-encoder picks the best

# ── Data structures ─────────────────────────────────────────────────────


@dataclass
class CurationCluster:
    """A topic-cohesive group of memories that warrants a single page."""

    topic: str  # e.g. "predictive-coding-gate" — derived from dominant entity
    domain: str  # cortex / agentic-ai / etc.
    suggested_kind: str  # reference / lesson / adr
    suggested_path: str  # e.g. "reference/cortex/predictive-coding-gate.md"
    memory_ids: list[int] = field(default_factory=list)
    memory_contents: list[str] = field(default_factory=list)
    memory_tags: list[list[str]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)  # top entities by frequency
    avg_heat: float = 0.0
    earliest_at: str = ""
    latest_at: str = ""


@dataclass
class CurationJob:
    """One authoring task: cluster + prompt ready for the LLM."""

    cluster: CurationCluster
    prompt: str
    related_pages: list[str] = field(default_factory=list)  # paths for [[wiki-links]]


# ── Topic identification ────────────────────────────────────────────────


_TOPIC_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "can", "this",
        "that", "these", "those", "to", "of", "for", "in", "on", "at",
        "by", "with", "from", "as", "into", "user", "tool", "command",
        "file", "output", "error", "input", "result", "decision", "lesson",
    }
)


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-")


_FILE_EXT_RE = re.compile(
    r"\b([\w./_-]+)\.(py|ts|js|md|sql|yml|yaml|toml|rs|go)\b"
)
_CAMEL_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:[A-Z][a-z]+)+\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _extract_entities_from_content(content: str) -> list[str]:
    """Crude entity extraction — proper nouns, file paths, function names.

    Canonicalisation:
      - File paths drop the extension (``foo/bar.py`` → ``bar``) so the
        same module mentioned with and without extension counts as the
        same entity.
      - File paths drop the directory prefix to keep cluster topics
        readable. The full path is still in the source memory.

    Mirrors mcp_server/core/knowledge_graph.py's heuristic NER but kept
    local to avoid coupling auto-curator to the knowledge-graph subsystem.
    """
    entities: list[str] = []
    # File-path-like tokens — canonicalise to the basename without extension
    for m in _FILE_EXT_RE.finditer(content):
        full = m.group(1)  # the part before the dot
        basename = full.rsplit("/", 1)[-1]
        if len(basename) >= 4:
            entities.append(basename)
    # CamelCase identifiers
    for m in _CAMEL_RE.finditer(content):
        entities.append(m.group(0))
    # snake_case identifiers ≥ 6 chars
    for m in _SNAKE_RE.finditer(content):
        if len(m.group(0)) >= 6:
            entities.append(m.group(0))
    return entities


def _cluster_topic_from_entities(entities: list[str]) -> str:
    """Pick a topic label from a list of entities (most-frequent wins)."""
    if not entities:
        return "untitled"
    c = Counter(entities)
    top = c.most_common(1)[0][0]
    # Strip extension if present
    return top.rsplit(".", 1)[0]


# ── Clustering ──────────────────────────────────────────────────────────


def build_clusters(
    memories: list[dict],
    *,
    domain: str | None = None,
    min_memories: int = MIN_MEMORIES_PER_CLUSTER,
    min_avg_heat: float = MIN_AVG_HEAT_FOR_PAGE,
) -> list[CurationCluster]:
    """Group memories into topic clusters via dominant-entity bucketing.

    Strategy:
      1. Extract entities from each memory's content.
      2. Assign each memory to its top entity (the one with highest
         document frequency within the memory's content).
      3. Group memories by assigned entity.
      4. Filter: clusters below ``min_memories`` or below
         ``min_avg_heat`` are dropped — they don't earn a page yet.

    Returns clusters sorted by combined size × avg_heat descending so
    high-value clusters are curated first.

    No LLM call here — this is pure logic. The LLM gets called downstream
    by the handler with the prompts ``build_authoring_prompt`` produces.
    """
    if not memories:
        return []

    # Step 1+2: assign each memory to its dominant entity
    buckets: dict[str, list[dict]] = defaultdict(list)
    for mem in memories:
        if domain and mem.get("domain") != domain:
            continue
        content = mem.get("content") or ""
        entities = _extract_entities_from_content(content)
        if not entities:
            continue
        # Dominant entity = most frequent
        top_entity = Counter(entities).most_common(1)[0][0]
        # Skip too-generic entities
        if top_entity.lower() in _TOPIC_STOPWORDS or len(top_entity) < 4:
            continue
        buckets[top_entity].append(mem)

    # Step 3+4: build clusters
    clusters: list[CurationCluster] = []
    for entity, mems in buckets.items():
        if len(mems) < min_memories:
            continue
        avg_heat = sum(m.get("effective_heat", m.get("heat", 0.0)) for m in mems) / len(mems)
        if avg_heat < min_avg_heat:
            continue
        # Aggregate all entities across cluster memories for richer context
        all_entities: list[str] = []
        for m in mems:
            all_entities.extend(_extract_entities_from_content(m.get("content") or ""))
        top_entities = [e for e, _ in Counter(all_entities).most_common(8)]
        topic = entity
        slug = _slugify(topic)
        # Pick kind heuristically — could be improved by tag inspection
        kind = _infer_kind(mems)
        dom = (mems[0].get("domain") or "cortex").lower()
        path = f"{_kind_dir(kind)}/{dom}/{slug}.md"
        clusters.append(
            CurationCluster(
                topic=topic,
                domain=dom,
                suggested_kind=kind,
                suggested_path=path,
                memory_ids=[m["id"] for m in mems if "id" in m],
                memory_contents=[m.get("content") or "" for m in mems],
                memory_tags=[m.get("tags") or [] for m in mems],
                entities=top_entities,
                avg_heat=avg_heat,
                earliest_at=min((m.get("created_at") or "") for m in mems),
                latest_at=max((m.get("created_at") or "") for m in mems),
            )
        )

    # Rank by size × avg_heat
    clusters.sort(key=lambda c: len(c.memory_ids) * c.avg_heat, reverse=True)
    return clusters


def _infer_kind(memories: list[dict]) -> str:
    """Decide whether the cluster is a reference, lesson, or adr."""
    tag_counter: Counter[str] = Counter()
    for m in memories:
        for t in m.get("tags") or []:
            tag_counter[t.lower()] += 1
    # Prefer explicit signals
    if tag_counter.get("decision", 0) > 0 or tag_counter.get("adr", 0) > 0:
        return "adr"
    if (
        tag_counter.get("lesson", 0) > 0
        or tag_counter.get("learned", 0) > 0
        or tag_counter.get("postmortem", 0) > 0
    ):
        return "lesson"
    return "reference"


def _kind_dir(kind: str) -> str:
    return {"adr": "adr", "lesson": "lessons", "reference": "reference"}.get(kind, "reference")


# ── Authoring-prompt construction ──────────────────────────────────────


WIKI_AUTHORING_PROMPT = """You are Opus 4.7 authoring a single wiki page for the Cortex persistent-memory MCP server.

You are given a topic-cohesive cluster of PG memories (tool events, decisions, lessons, notes) plus the suggested wiki path and any existing related wiki pages for cross-linking.

# Your task

Author **one** curated wiki page in Markdown that follows the Cortex documentation conventions below. The page must be substantive (target 8-15 KB), with structure, prose, diagrams, and citations. Do **not** produce a mechanical template. Do **not** dump raw memory content; synthesise.

# Output format

Output **only** the wiki page body, starting with YAML frontmatter, then the body. No preamble, no explanation, no surrounding fences.

# Frontmatter (required)

```yaml
---
title: <short specific title — not "Reference: X", just "X">
kind: {kind}
domain: {domain}
status: living
authored_by: Opus 4.7
created: {today}
last_reviewed: {today}
audience: [developer, ...]
---
```

# Required structural sections (in this order)

1. **# <title>** — H1 matching frontmatter title.
2. **Lead paragraph** — one paragraph that says what the page is and why a reader should care.
3. **Sections explaining the topic**:
   - Use ```mermaid fences for flowcharts, sequence diagrams, state diagrams when the topic involves dataflow or state transitions.
   - Use tables for taxonomies, parameter lists, comparisons.
   - Use ``` fences with language for code snippets.
   - Cite specific source files with full paths (e.g. ``mcp_server/core/predictive_coding_gate.py``).
4. **## Why this design and not the alternatives** — explain the architectural choice. What was considered, what was rejected, why.
5. **## What can go wrong** — failure modes the next reader should know about, with concrete symptoms.
6. **## See also** — cross-links to related pages using `[[wiki/path]]` notation, plus specific source files.
7. **## Primary sources** — if the topic touches research literature, cite the actual papers with full citations.

# Conventions

- Write authoritative declarative prose. No filler ("It's worth noting that..."). State facts directly.
- When a number is given, name its source ("p50 latency 125ms — measured in benchmarks/longmemeval/run_benchmark.py 2026-04").
- When the topic has biological inspiration, name the paper that motivated the design.
- Don't repeat what's already in [[reference/cortex/architecture-overview]] — link to it.
- Each diagram must add information that the table or prose cannot convey efficiently.
- No phrases like "in this section we will" — just say it.

# The cluster

**Topic**: {topic}
**Suggested wiki path**: {suggested_path}
**Domain**: {domain}
**Memory count**: {n_memories}
**Top entities in cluster**: {entities}

**Existing related wiki pages** (for cross-linking via `[[path]]`):
{related_pages_block}

**Memories in this cluster** (synthesise — do not dump):

{memories_block}

---

Author the wiki page now. Output only the Markdown body, frontmatter first.
"""


def build_authoring_prompt(
    cluster: CurationCluster,
    related_pages: list[str],
    today: str = "",
) -> str:
    """Construct the structured prompt for an LLM to author the cluster's page.

    The prompt encodes the same conventions the hand-authored 2026-05-17
    pages followed. Returning the prompt as a string (vs. calling an LLM
    here) keeps this module pure and lets the caller pick the LLM
    integration: ``curate_wiki`` returns the prompts for the in-session
    LLM, or a future ``llm_client.author_page(prompt)`` adapter sends
    them directly to the Anthropic API.
    """
    today = today or "2026-05-17"
    # Build memories block — truncate each memory body to fit within
    # the prompt budget, but never to a misleading degree.
    capped = cluster.memory_contents[:MAX_MEMORIES_PER_PROMPT]
    mem_blocks: list[str] = []
    for idx, content in enumerate(capped, 1):
        tags = cluster.memory_tags[idx - 1] if idx - 1 < len(cluster.memory_tags) else []
        head = content[:1200].rstrip()
        if len(content) > 1200:
            head += "\n...[memory truncated, full content available via recall]"
        tag_str = (", ".join(tags) if tags else "(no tags)")
        mem_blocks.append(f"### Memory {idx} (tags: {tag_str})\n\n{head}")
    memories_block = "\n\n".join(mem_blocks) if mem_blocks else "(none — cluster filtered out)"

    related_block = (
        "\n".join(f"- [[{p}]]" for p in related_pages) if related_pages else "(none yet — this is a fresh topic)"
    )

    return WIKI_AUTHORING_PROMPT.format(
        kind=cluster.suggested_kind,
        domain=cluster.domain,
        today=today,
        topic=cluster.topic,
        suggested_path=cluster.suggested_path,
        n_memories=len(cluster.memory_ids),
        entities=", ".join(cluster.entities[:8]) or "(none extracted)",
        related_pages_block=related_block,
        memories_block=memories_block,
    )


def build_jobs(
    clusters: list[CurationCluster],
    existing_pages_by_topic: dict[str, list[str]] | None = None,
    today: str = "",
) -> list[CurationJob]:
    """Pair each cluster with its authoring prompt and any related pages."""
    existing_pages_by_topic = existing_pages_by_topic or {}
    jobs: list[CurationJob] = []
    for cl in clusters:
        related = _find_related_pages(cl, existing_pages_by_topic)
        prompt = build_authoring_prompt(cl, related, today=today)
        jobs.append(CurationJob(cluster=cl, prompt=prompt, related_pages=related))
    return jobs


def _find_related_pages(
    cluster: CurationCluster,
    existing_pages_by_topic: dict[str, list[str]],
) -> list[str]:
    """Find existing wiki pages whose topic words overlap with this cluster's."""
    related: list[str] = []
    topic_tokens = set(re.findall(r"[a-z0-9]+", cluster.topic.lower()))
    topic_tokens.update(re.findall(r"[a-z0-9]+", " ".join(cluster.entities).lower()))
    seen: set[str] = set()
    for existing_topic, paths in existing_pages_by_topic.items():
        et_tokens = set(re.findall(r"[a-z0-9]+", existing_topic.lower()))
        if topic_tokens & et_tokens:
            for p in paths:
                if p not in seen and p != cluster.suggested_path:
                    related.append(p)
                    seen.add(p)
    return related[:6]
