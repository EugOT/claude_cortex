"""Handler: recall -- PG recall + production enrichments.

Composition root wiring infrastructure to core retrieval logic.

Base retrieval uses pg_recall (intent-adaptive PG WRRF + FlashRank reranking).
Production enrichments layer on top: prospective memory injection,
co-activation Hebbian learning, neuro-symbolic rules, strategic ordering.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import memory_rules
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.core.knowledge_graph import extract_entities
from mcp_server.core.pg_recall import recall as pg_recall
from mcp_server.core.query_intent import QueryIntent, classify_query_intent
from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.handlers.recall_helpers import (
    build_enhancements,
    filter_by_tags,
    filter_low_signal,
    inject_triggered_memories,
)
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import (
    get_memory_settings,
    root_agent_topic,
)
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store

schema = {
    "title": "Recall (retrieve memories)",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["memories"],
        "properties": {
            "memories": {
                "type": "array",
                "description": "Ranked list of matching memories. Best result is index 0.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Memory UUID."},
                        "content": {"type": "string", "description": "Memory body."},
                        "score": {
                            "type": "number",
                            "description": "Final fused + reranked score.",
                        },
                        "heat": {
                            "type": "number",
                            "description": "Current thermodynamic heat [0,1].",
                        },
                        "domain": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "created_at": {"type": "string", "format": "date-time"},
                        "source": {"type": "string"},
                        "truncated": {
                            "type": "boolean",
                            "description": (
                                "Present and true when content was cut to fit "
                                "the response budget. Fetch the full body via "
                                "the memory_id argument."
                            ),
                        },
                        "content_length": {
                            "type": "integer",
                            "description": "Original content size in chars (set when truncated).",
                        },
                    },
                },
            },
            "intent": {
                "type": "string",
                # source: mcp_server/core/query_intent.py::QueryIntent — every
                # value the classifier can emit must be in this enum or MCP
                # output validation rejects the response. Previously the
                # schema was narrower than the classifier's range, so any
                # query falling back to QueryIntent.GENERAL ("general")
                # failed validation. Issue #46.
                "enum": [
                    "temporal",
                    "causal",
                    "semantic",
                    "entity",
                    "knowledge_update",
                    "multi_hop",
                    "instruction",
                    "event_order",
                    "summarization",
                    "preference",
                    "general",
                ],
                "description": "Classified query intent that drove the signal-weight profile.",
            },
            "count": {"type": "integer", "description": "Number of memories returned."},
        },
    },
    "description": (
        "Retrieve memories from the Cortex store using intent-adaptive PG "
        "recall (server-side WRRF fusion of vector + FTS + trigram + heat + "
        "recency) followed by FlashRank cross-encoder reranking and "
        "production enrichments (prospective memory injection, Hebbian "
        "co-activation strengthening, neuro-symbolic rules, strategic ordering "
        "to mitigate Lost-in-the-Middle, Liu et al. 2023). Use this before "
        "any non-trivial work to check what Cortex already knows; running "
        "blind is unacceptable when recall takes ~200ms. Distinct from "
        "`recall_hierarchical` (returns the L0/L1/L2 cluster topology, not "
        "a flat ranked list), `navigate_memory` (graph BFS over co-access "
        "edges from one seed memory), and `get_causal_chain` (entity-graph "
        "traversal, not memory recall). Returns ranked memories with scores, "
        "heat, and source."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language query describing what to retrieve. Free "
                    "text; intent (temporal/causal/semantic/entity/multi-hop) "
                    "is auto-classified to weight the WRRF signals."
                ),
                "examples": [
                    "why did we choose pgvector over Pinecone?",
                    "failed attempts to fix recall regression",
                    "what does the consolidate handler do?",
                ],
            },
            "domain": {
                "type": "string",
                "description": (
                    "Restrict results to a single cognitive domain. Omit to "
                    "search across all domains."
                ),
                "examples": ["cortex", "auth-service"],
            },
            "directory": {
                "type": "string",
                "description": (
                    "Restrict results to memories tagged with a specific "
                    "absolute project directory."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of ranked memories to return after reranking."
                ),
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "examples": [5, 10, 25],
            },
            "min_heat": {
                "type": "number",
                "description": (
                    "Minimum heat (0.0-1.0) for a memory to be considered. "
                    "Lower = include colder/older memories. Use 0 to include everything."
                ),
                "default": 0.05,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.0, 0.05, 0.3],
            },
            "agent_topic": {
                "type": "string",
                "description": (
                    "Restrict to memories produced under a specific agent "
                    "context tag (subagent topic isolation)."
                ),
                "examples": ["engineer", "researcher", "reviewer"],
            },
            "include_low_signal": {
                "type": "boolean",
                "description": (
                    "When false (default), drops memories tagged as auto-"
                    "captures (``auto-captured``, ``tool:edit``, ``_backfill``, "
                    "``stage-N``, ``session-summary``, …) so curated content "
                    "(ADRs, lessons, conventions) surfaces in the first few "
                    "results. Spike 2026-05-13 showed unfiltered recall is "
                    "drowned by tool-output captures even for queries about "
                    "design decisions. Set true for debugging / replay "
                    "tooling that needs the raw memory feed."
                ),
                "default": False,
            },
            "tags_any": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Positive tag filter (OR): keep only memories that carry "
                    "at least one of the listed tags. Applied after the WRRF "
                    "recall pipeline, at the same stage as the low-signal "
                    'filter. Pass ``tags_any=["archival"]`` to retrieve only '
                    "archival-tier memories."
                ),
                "default": [],
                "examples": [["archival"], ["lesson", "decision"]],
            },
            "tags_all": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Positive tag filter (AND): keep only memories that carry "
                    "ALL of the listed tags. Applied after the WRRF recall "
                    "pipeline, at the same stage as the low-signal filter."
                ),
                "default": [],
                "examples": [["archival", "scope:engineer"]],
            },
            "memory_id": {
                "type": "integer",
                "description": (
                    "Fetch one memory by id, bypassing search. Use to "
                    "retrieve the full content of a result that came back "
                    "with ``truncated: true``. ``query`` is ignored when "
                    "set (still required by the schema; pass the id as a "
                    "string if nothing better)."
                ),
            },
            "content_offset": {
                "type": "integer",
                "description": (
                    "With ``memory_id``: start the returned content at this "
                    "character offset. Page through contents larger than "
                    "the response budget by re-calling with the previous "
                    "offset + the length of the slice received."
                ),
                "default": 0,
                "minimum": 0,
            },
        },
    },
}

_store: MemoryStore | None = None
_momentum_state: dict = {"momentum": 0.5}


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _apply_strategic_ordering(
    results: list[dict],
    top_fraction: float = 0.3,
    bottom_fraction: float = 0.2,
) -> list[dict]:
    """Reorder to mitigate 'Lost in the Middle' (Liu et al. 2023)."""
    n = len(results)
    if n < 5:
        return results
    top_n = max(1, int(n * top_fraction))
    bottom_n = max(1, int(n * bottom_fraction))
    if n - top_n - bottom_n <= 0:
        return results
    return results[:top_n] + results[n - bottom_n :] + results[top_n : n - bottom_n]


def _apply_co_activation(
    results: list[dict], store: MemoryStore, settings: Any
) -> None:
    """Dragon Hatchling Hebbian: co-retrieved entities strengthen edges."""
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.CO_ACTIVATION):
        # No-op: do not strengthen co-retrieved entity edges.
        return
    if not settings.CO_ACTIVATION_ENABLED or len(results) < 2:
        return
    min_score = settings.CO_ACTIVATION_MIN_SCORE
    lr = settings.CO_ACTIVATION_LEARNING_RATE
    entity_sets: list[set[str]] = []
    for r in results[:5]:
        if r.get("score", 0) < min_score:
            continue
        ents = extract_entities(r.get("content", ""))
        entity_sets.append({e["name"] for e in ents})
    try:
        for i, ents_a in enumerate(entity_sets):
            for ents_b in entity_sets[i + 1 :]:
                for a in list(ents_a)[:5]:
                    for b in list(ents_b)[:5]:
                        if a != b:
                            store.reinforce_or_create_relationship(a, b, lr)
    except Exception:
        pass


def _apply_rules_and_order(
    results: list[dict], store: MemoryStore, settings: Any, max_results: int
) -> list[dict]:
    """Apply neuro-symbolic rules and strategic ordering."""
    try:
        rules = store.get_all_active_rules()
        if rules:
            results = memory_rules.apply_rules(results, rules, score_field="score")
    except Exception:
        pass
    results = results[:max_results]
    if settings.STRATEGIC_ORDERING_ENABLED:
        results = _apply_strategic_ordering(
            results, settings.STRATEGIC_TOP_FRACTION, settings.STRATEGIC_BOTTOM_FRACTION
        )
    return results


def _track_recall_replay(results: list[dict], store: Any) -> None:
    """Increment access_count and replay_count for recalled memories.

    Each recall event counts as a hippocampal replay (McClelland 1995).
    This drives consolidation stage advancement through the cascade.
    """
    for mem in results:
        mem_id = mem.get("memory_id") or mem.get("id")
        if mem_id is None:
            continue
        try:
            store.update_memory_access(mem_id)
            store.increment_replay_count(mem_id)
        except Exception:
            pass


def _fetch_by_id(memory_id: int, content_offset: int) -> dict[str, Any]:
    """Fetch one memory by id — the retrieval path for truncated results.

    ``content_offset`` pages through contents larger than the response
    budget: the slice starts there, ``content_length`` carries the full
    size, and ``bound_payload`` marks the slice ``truncated`` if it
    still overflows.
    """
    stored = _get_store().get_memory(memory_id)
    if stored is None:
        return {"memories": [], "count": 0, "intent": "general"}
    # Copy before mutating: truncation must never write back into
    # whatever object the store handed us.
    memory = {**stored}
    content = memory.get("content") or ""
    if content_offset > 0:
        memory["content"] = content[content_offset:]
    memory["content_length"] = len(content)
    memory["content_offset"] = content_offset
    resp = {"memories": [memory], "count": 1, "intent": "general"}
    settings = get_memory_settings()
    return bound_payload(
        resp, [ListTarget("memories", weight_key="score")], settings.MAX_RESPONSE_CHARS
    )


async def _handler_impl(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retrieve memories: pg_recall base + production enrichments."""
    if args and args.get("memory_id") is not None:
        return _fetch_by_id(
            int(args["memory_id"]), int(args.get("content_offset") or 0)
        )
    if not args or not args.get("query"):
        # Issue #46: even the early-return must satisfy the outputSchema's
        # required keys (`memories`).
        return {
            "memories": [],
            "count": 0,
            "intent": "semantic",
        }

    query = args["query"]
    domain, directory = args.get("domain"), args.get("directory")
    agent_topic = args.get("agent_topic")
    # Connection-rooted scoping: when the server is launched with
    # CORTEX_ROOT_AGENT_TOPIC, force that scope regardless of what the
    # caller passed (or omitted). Defense at the handler boundary covers
    # every caller, not just the schema-stripped tool surface.
    _root = root_agent_topic()
    if _root is not None:
        agent_topic = _root
    max_results = args.get("max_results", 10)
    min_heat = args.get("min_heat", 0.05)
    include_low_signal = bool(args.get("include_low_signal", False))
    tags_any: list[str] = list(args.get("tags_any") or [])
    tags_all: list[str] = list(args.get("tags_all") or [])
    settings = get_memory_settings()
    store, emb = _get_store(), get_embedding_engine()

    # Base retrieval: pg_recall (intent → PG weights → recall_memories → rerank).
    # Over-fetch when filtering is on so that after low-signal drops we
    # still surface ``max_results`` curated items. Tool-output captures
    # are common enough that a 3× headroom is a reasonable starting
    # point — the alternative is iterative refill, which complicates
    # the rerank ordering.
    fetch_k = max_results * 3 if not include_low_signal else max_results
    results = pg_recall(
        query=query,
        store=store,
        embeddings=emb,
        top_k=fetch_k,
        domain=domain,
        directory=directory,
        agent_topic=agent_topic,
        min_heat=min_heat,
        wrrf_k=settings.WRRF_K,
        momentum_state=_momentum_state,
    )

    # Low-signal filter (spike 2026-05-13). Tool-output captures,
    # backfilled imports, and stage reports dominate unfiltered recall
    # even for queries about design decisions, drowning out curated
    # ADRs / lessons / conventions. Filter unless the caller opts in.
    low_signal_dropped = 0
    if not include_low_signal:
        results, low_signal_dropped = filter_low_signal(results)

    # Positive tag filter: tags_any (OR) and tags_all (AND).
    # Applied at the same pipeline stage as the low-signal filter so the
    # over-fetch headroom above still applies.
    if tags_any or tags_all:
        results = filter_by_tags(results, tags_any, tags_all)

    # Cap to the caller-requested max_results after filtering.
    results = results[:max_results]

    # Production enrichments on top of base retrieval
    results = inject_triggered_memories(results, query, store, max_inject=max_results)
    _apply_co_activation(results, store, settings)
    results = _apply_rules_and_order(results, store, settings, max_results)

    # Track access + replay for consolidation cascade
    # Biological basis: retrieval = hippocampal replay (McClelland 1995)
    # Each recall increments replay_count, driving stage advancement
    _track_recall_replay(results, store)

    intent_info = classify_query_intent(query)
    intent = intent_info.get("intent", QueryIntent.GENERAL)
    # The legacy `results`/`total`/`query_intent` aliases byte-duplicated
    # every memory on the wire (measured: 815KB response for 15 memories,
    # 50% pure duplication — 2026-06-09 audit). All consumers now read the
    # schema-aligned keys.
    resp = {
        "memories": results,
        "count": len(results),
        "intent": str(intent),
        "low_signal_dropped": low_signal_dropped,
        "dispatch_tier": "pg",
        "signals": {},
        "enhancements": build_enhancements(query, intent, "pg", settings),
    }
    # Bounded I/O: the host rejects tool results over its token cap
    # (core/response_budget.py docstring for the measured derivation).
    # Truncated items keep their id; full content via the memory_id arg.
    resp = bound_payload(
        resp, [ListTarget("memories", weight_key="score")], settings.MAX_RESPONSE_CHARS
    )
    resp["count"] = len(resp["memories"])
    return resp


# Telemetry-instrumented public entry. Wrapper records latency, byte
# volume, and result count per call (Popper C6 read/write ratio audit).
handler = instrument("recall", _handler_impl, result_count_key="memories")
