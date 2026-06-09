"""Bounded MCP responses — total payload budget with per-item truncation.

An MCP tool response that exceeds the host's tool-result ceiling is
rejected wholesale and dumped to a file (Claude Code behaviour, observed
2026-06-10: recall response of 324,429 chars rejected). Bounding must
therefore happen on our side of the wire, where we control which bytes
survive.

Budget derivation (measured, not invented):

- Claude Code enforces ``MAX_MCP_OUTPUT_TOKENS`` on MCP tool results.
  source: Claude Code 2.1.170 binary, extracted 2026-06-10 —
    default   ``d4O = 25000`` tokens,
    estimator ``Xz(text) = round(len(text) / 4)`` (4 chars/token),
    char cap  ``l4O() = limit * 4`` → 100,000 chars.
- The counted text is the compact-JSON serialization of the payload:
  ``len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))``
  reproduced Claude Code's reported count exactly (324,429 == 324,429,
  measured 2026-06-10 on a rejected recall response).
- Safety factor 0.75 applied to the host cap. The host counts JS
  ``String.length`` (UTF-16 code units) while Python ``len()`` counts
  code points — non-BMP characters (emoji, rare CJK) count 2:1, so a
  payload filled exactly to the host cap can overshoot it. The factor
  guarantees no overshoot up to a 1/3 non-BMP code-point fraction
  (host_len = len × (1 + f) ≤ cap ⟺ f ≤ 1/3 at 0.75), far above any
  observed payload. source: ContextManager.swift budget logic
  (``reasoner.contextWindowSize * 0.75``), ai-prd-builder commit
  462de01 (2025-09-30) — same estimator-divergence guard, reused here
  per author direction.
- Secondary bound: ~1 MB MCP frame ceiling (measured 2026-04-23, see
  handlers/query_workflow_graph.py) — the Claude Code cap binds first.

Truncation policy: priority-weighted water-filling. A hard cap that
cuts all items equally destroys exactly the high-relevance content the
response exists to deliver, so the surviving budget is allocated
proportionally to each item's retrieval priority (``score`` from WRRF +
rerank fusion, ``heat`` for hot memories) and the least relevant slots
are condensed first. source: ContextDecomposer allocation algorithm,
ai-prd-builder commit 462de01 (2025-09-30) — "allocate remaining budget
proportionally across priority-ranked slots; condense
highest-priority-number [least important] slots first; iteratively
[shrink] the least important slot until the prompt fits". Adaptation:
slot priority = retrieval score (the system's own relevance estimate);
equal weights reduce to plain max-min fairness (the unweighted case).

Truncated items carry ``truncated: True`` plus ``content_length``
(original size) and keep their id, so truncation is never a dead end:
full content stays dynamically loadable by id (``recall`` ``memory_id``
+ ``content_offset`` args, ``wiki_read`` ``offset`` arg).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

# source: Claude Code 2.1.170 binary (see module docstring) —
# MAX_MCP_OUTPUT_TOKENS default 25000 tokens × 4 chars/token.
HOST_CAP_CHARS = 100_000

# source: ai-prd-builder ContextManager.swift, commit 462de01 (see module
# docstring) — guards the UTF-16-units vs code-points estimator divergence.
SAFETY_FACTOR = 0.75

MAX_RESPONSE_CHARS = int(HOST_CAP_CHARS * SAFETY_FACTOR)


@dataclass(frozen=True)
class ListTarget:
    """A list of dict items under ``payload[key]``, each carrying a text
    field at ``content_key`` that may be truncated.

    ``weight_key`` names a positive-number field used as the item's
    truncation priority (higher = keeps more content). ``None`` means
    equal shares."""

    key: str
    content_key: str = "content"
    weight_key: str | None = None


@dataclass(frozen=True)
class TextTarget:
    """A single string field at ``payload[key]`` that may be truncated."""

    key: str


@dataclass
class _Cell:
    """One truncatable text plus the bookkeeping keys written on cut."""

    container: dict
    content_key: str
    flag_key: str
    length_key: str
    weight: float = 1.0


def serialized_length(payload: Any) -> int:
    """Char count of the payload exactly as the MCP host counts it.

    Compact separators + ensure_ascii=False reproduce the host's count
    (verified char-exact against a rejected response, 2026-06-10).
    ``default=str`` mirrors lossy-but-total serialization of exotic
    values; handlers ship JSON-native types so it never fires in practice.
    """
    return len(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
    )


def bound_payload(
    payload: dict,
    targets: list[ListTarget | TextTarget],
    budget_chars: int = MAX_RESPONSE_CHARS,
) -> dict:
    """Mutate ``payload`` in place until it serializes within budget.

    Passes: (1) water-fill truncation of target texts; (2) if every
    target text is already empty, drop list items from the tail; (3) if
    nothing is left to cut, return the payload as-is (a metadata-only
    overflow is a bug upstream, not something to mask here).
    Terminates: every pass strictly shrinks the payload or exhausts
    cuttable material.
    """
    while True:
        total = serialized_length(payload)
        if total <= budget_chars:
            return payload
        cells = _collect_cells(payload, targets)
        cuttable = [c for c in cells if len(c.container.get(c.content_key) or "") > 0]
        if cuttable:
            _truncate_cells(cuttable, total - budget_chars)
            continue
        if not _drop_tail_item(payload, targets):
            return payload


def _collect_cells(
    payload: dict, targets: list[ListTarget | TextTarget]
) -> list[_Cell]:
    cells: list[_Cell] = []
    for target in targets:
        if isinstance(target, TextTarget):
            if isinstance(payload.get(target.key), str):
                cells.append(
                    _Cell(
                        container=payload,
                        content_key=target.key,
                        flag_key=f"{target.key}_truncated",
                        length_key=f"{target.key}_length",
                    )
                )
            continue
        items = payload.get(target.key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and isinstance(item.get(target.content_key), str):
                cells.append(
                    _Cell(
                        container=item,
                        content_key=target.content_key,
                        flag_key="truncated",
                        length_key=f"{target.content_key}_length",
                        weight=_priority_weight(item, target.weight_key),
                    )
                )
    return cells


def _priority_weight(item: dict, weight_key: str | None) -> float:
    """Item's truncation priority; degenerate values fall back to 1.0
    (equal share — the unweighted behavior, not an invented constant)."""
    if weight_key is None:
        return 1.0
    value = item.get(weight_key)
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return float(value)
    return 1.0


def _flag_cost(cell: _Cell) -> int:
    """Exact serialized chars added when a cell is first marked truncated."""
    cost = 0
    if not cell.container.get(cell.flag_key):
        cost += len(f',"{cell.flag_key}":true')
    if cell.length_key not in cell.container:
        content = cell.container.get(cell.content_key) or ""
        cost += len(f',"{cell.length_key}":') + len(str(len(content)))
    return cost


def _truncate_cells(cells: list[_Cell], overflow: int) -> None:
    """Weighted water-fill: cut contents down to a common per-weight
    level L — each cell keeps up to ``floor(L × weight)`` chars — so the
    freed raw chars cover ``overflow`` plus the exact cost of the flags
    added in the worst case (every cell gets marked). Survivor budget is
    thus proportional to priority and low-priority cells condense first
    (ContextDecomposer allocation; see module docstring).

    Each raw content char occupies ≥1 serialized char (escapes only
    widen), so freeing N raw chars frees ≥N serialized chars; floor()
    only ever cuts deeper, preserving the guarantee.
    """
    needed = overflow + sum(_flag_cost(c) for c in cells)
    pairs = [(len(c.container[c.content_key]), c.weight) for c in cells]
    level = _water_level(pairs, needed)
    for cell in cells:
        content = cell.container[cell.content_key]
        allowed = int(level * cell.weight)
        if len(content) <= allowed:
            continue
        cell.container[cell.flag_key] = True
        # Never clobber a caller-set length (wiki_read pre-sets the full
        # page size so offset-paging works across truncated slices).
        cell.container.setdefault(cell.length_key, len(content))
        cell.container[cell.content_key] = content[:allowed]


def _water_level(pairs: list[tuple[int, float]], needed: int) -> float:
    """Largest common level L ≥ 0 with
    ``sum(max(0, length - L*weight)) >= needed``.

    Weighted max-min fairness: cells whose length exceeds L×weight are
    cut to it, the rest are untouched. Equal weights make this plain
    water-filling. Returns 0 when even emptying everything cannot free
    ``needed`` chars.
    """
    if not pairs or needed <= 0:
        return max((length / weight for length, weight in pairs), default=0.0)
    desc = sorted(pairs, key=lambda p: p[0] / p[1], reverse=True)
    freed = 0.0
    active_weight = 0.0
    for i, (length, weight) in enumerate(desc):
        ratio = length / weight
        active_weight += weight
        nxt = desc[i + 1] if i + 1 < len(desc) else None
        next_ratio = nxt[0] / nxt[1] if nxt else 0.0
        capacity = active_weight * (ratio - next_ratio)
        if freed + capacity >= needed:
            return ratio - (needed - freed) / active_weight
        freed += capacity
    return 0.0


def _drop_tail_item(payload: dict, targets: list[ListTarget | TextTarget]) -> bool:
    """Drop one item from the tail of the longest target list.

    Tail = lowest-ranked entry of the shipped ordering. Records the
    running total in ``payload["truncation_dropped"]`` so callers can
    surface that the list was cut. Returns False when no list has items.
    """
    longest: list | None = None
    for target in targets:
        if isinstance(target, ListTarget):
            items = payload.get(target.key)
            if isinstance(items, list) and items:
                if longest is None or len(items) > len(longest):
                    longest = items
    if longest is None:
        return False
    longest.pop()
    payload["truncation_dropped"] = payload.get("truncation_dropped", 0) + 1
    return True
