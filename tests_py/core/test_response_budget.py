"""Tests for core/response_budget — bounded MCP responses.

Budget source (measured): Claude Code 2.1.170 binary —
MAX_MCP_OUTPUT_TOKENS default 25000 tokens × 4 chars/token = 100,000
chars of compact-JSON payload. See the module docstring for the full
derivation and char-exact verification protocol.
"""

from __future__ import annotations

import json

from mcp_server.core.response_budget import (
    HOST_CAP_CHARS,
    MAX_RESPONSE_CHARS,
    SAFETY_FACTOR,
    ListTarget,
    TextTarget,
    _water_level,
    bound_payload,
    serialized_length,
)


def _mem(mid: int, content: str, **extra) -> dict:
    return {"id": mid, "content": content, "score": 0.5, **extra}


# ── serialized_length ─────────────────────────────────────────────────


def test_serialized_length_matches_compact_json() -> None:
    payload = {"memories": [_mem(1, "héllo\nworld")], "count": 1}
    expected = len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    assert serialized_length(payload) == expected


def test_serialized_length_counts_chars_not_bytes() -> None:
    # The host counts JS string length (chars); UTF-8 bytes would be more.
    payload = {"content": "é" * 10}
    assert serialized_length(payload) == len('{"content":"' + "é" * 10 + '"}')


# ── _water_level ──────────────────────────────────────────────────────


def test_water_level_single_text() -> None:
    assert _water_level([(10, 1.0)], 3) == 7  # frees exactly 3


def test_water_level_cuts_largest_first() -> None:
    # [10, 4, 2], need 6: level 4 frees 6 from the largest alone.
    level = _water_level([(10, 1.0), (4, 1.0), (2, 1.0)], 6)
    assert level == 4
    assert sum(max(0, ln - level) for ln in [10, 4, 2]) >= 6


def test_water_level_spreads_across_ties() -> None:
    level = _water_level([(10, 1.0), (10, 1.0)], 4)
    assert level == 8
    assert sum(max(0, ln - level) for ln in [10, 10]) >= 4


def test_water_level_zero_when_insufficient() -> None:
    assert _water_level([(3, 1.0), (2, 1.0)], 100) == 0


def test_water_level_no_cut_needed() -> None:
    assert _water_level([(5, 1.0), (3, 1.0)], 0) == 5


def test_water_level_weighted_cuts_low_priority_first() -> None:
    # Equal lengths, weights 2:1 — the low-weight cell has the higher
    # length/weight ratio, so it absorbs the whole cut.
    level = _water_level([(100, 2.0), (100, 1.0)], 30)
    assert level == 70
    # allowed = level * weight: heavy cell keeps all 100 (140 > 100).
    assert int(level * 2.0) >= 100
    assert int(level * 1.0) == 70


# ── bound_payload ─────────────────────────────────────────────────────


def test_noop_under_budget() -> None:
    payload = {"memories": [_mem(1, "short")], "count": 1}
    before = json.loads(json.dumps(payload))
    out = bound_payload(payload, [ListTarget("memories")], budget_chars=10_000)
    assert out == before
    assert "truncated" not in out["memories"][0]


def test_truncates_to_budget_and_marks_items() -> None:
    fat = "x" * 50_000
    payload = {"memories": [_mem(1, fat), _mem(2, fat)], "count": 2}
    out = bound_payload(payload, [ListTarget("memories")], budget_chars=5_000)
    assert serialized_length(out) <= 5_000
    for item in out["memories"]:
        assert item["truncated"] is True
        assert item["content_length"] == 50_000
        assert item["id"] in (1, 2)  # id survives for fetch-by-id


def test_small_items_survive_intact() -> None:
    small = "curated lesson"
    payload = {
        "memories": [_mem(1, "x" * 50_000), _mem(2, small)],
        "count": 2,
    }
    out = bound_payload(payload, [ListTarget("memories")], budget_chars=5_000)
    assert out["memories"][1]["content"] == small
    assert "truncated" not in out["memories"][1]
    assert out["memories"][0]["truncated"] is True


def test_text_target_truncation() -> None:
    payload = {"context": "c" * 20_000, "domain": "cortex"}
    out = bound_payload(payload, [TextTarget("context")], budget_chars=2_000)
    assert serialized_length(out) <= 2_000
    assert out["context_truncated"] is True
    assert out["context_length"] == 20_000


def test_preset_length_key_is_not_clobbered() -> None:
    # wiki_read pre-sets content_length to the FULL page size before
    # slicing at offset; truncation must not overwrite it.
    payload = {"content": "y" * 10_000, "content_length": 99_999}
    out = bound_payload(payload, [TextTarget("content")], budget_chars=1_000)
    assert out["content_truncated"] is True
    assert out["content_length"] == 99_999


def test_mixed_targets_share_one_budget() -> None:
    payload = {
        "hotMemories": [_mem(1, "h" * 10_000)],
        "firedTriggers": [{"id": 7, "content": "t" * 10_000}],
        "context": "c" * 10_000,
    }
    out = bound_payload(
        payload,
        [
            ListTarget("hotMemories"),
            ListTarget("firedTriggers"),
            TextTarget("context"),
        ],
        budget_chars=6_000,
    )
    assert serialized_length(out) <= 6_000


def test_drops_tail_items_when_contents_exhausted() -> None:
    # Metadata-heavy items with empty contents: only dropping helps.
    items = [_mem(i, "", note="m" * 200) for i in range(50)]
    payload = {"memories": items, "count": 50}
    out = bound_payload(payload, [ListTarget("memories")], budget_chars=2_000)
    assert serialized_length(out) <= 2_000
    assert out["truncation_dropped"] > 0
    assert len(out["memories"]) < 50
    # Tail (lowest-ranked) dropped first — head survives.
    assert out["memories"][0]["id"] == 0


def test_metadata_only_overflow_returns_payload_unmasked() -> None:
    # Nothing cuttable and no list items: returned as-is (upstream bug,
    # not masked here).
    payload = {"blob": "z" * 5_000}
    out = bound_payload(payload, [ListTarget("memories")], budget_chars=100)
    assert out["blob"] == "z" * 5_000


def test_escaped_content_still_lands_under_budget() -> None:
    # Newlines/quotes serialize to 2 chars each; the re-measure loop
    # must converge below budget regardless.
    payload = {"memories": [_mem(1, '"\n' * 20_000)], "count": 1}
    out = bound_payload(payload, [ListTarget("memories")], budget_chars=3_000)
    assert serialized_length(out) <= 3_000


def test_score_weighted_truncation_preserves_relevant_content() -> None:
    # ContextDecomposer allocation (ai-prd-builder 462de01): budget is
    # proportional to slot priority — here the retrieval score. A 9:1
    # score ratio must yield ~9:1 surviving content, not an equal cut.
    payload = {
        "memories": [
            _mem(1, "a" * 10_000, score=0.9),
            _mem(2, "b" * 10_000, score=0.1),
        ],
        "count": 2,
    }
    out = bound_payload(
        payload, [ListTarget("memories", weight_key="score")], budget_chars=4_000
    )
    assert serialized_length(out) <= 4_000
    kept_high = len(out["memories"][0]["content"])
    kept_low = len(out["memories"][1]["content"])
    assert kept_low > 0  # low priority condensed, not erased
    assert 8.0 <= kept_high / kept_low <= 10.0  # ≈ score ratio 9, ± rounding
    assert out["memories"][0]["truncated"] is True
    assert out["memories"][1]["truncated"] is True


def test_degenerate_weights_fall_back_to_equal_shares() -> None:
    # Missing / zero / negative / NaN scores must not crash or starve
    # an item — they get weight 1.0 (the unweighted behavior).
    payload = {
        "memories": [
            {"id": 1, "content": "x" * 5_000},
            {"id": 2, "content": "y" * 5_000, "score": 0},
            {"id": 3, "content": "z" * 5_000, "score": -2.0},
            {"id": 4, "content": "w" * 5_000, "score": float("nan")},
        ],
        "count": 4,
    }
    out = bound_payload(
        payload, [ListTarget("memories", weight_key="score")], budget_chars=4_000
    )
    assert serialized_length(out) <= 4_000
    lengths = [len(m["content"]) for m in out["memories"]]
    assert max(lengths) - min(lengths) <= 1  # equal shares ± floor()


def test_default_budget_is_host_cap_times_safety_factor() -> None:
    # source: Claude Code 2.1.170 binary — 25000 tokens × 4 chars/token;
    # × 0.75 safety factor (ai-prd-builder ContextManager.swift, 462de01).
    assert HOST_CAP_CHARS == 100_000
    assert SAFETY_FACTOR == 0.75
    assert MAX_RESPONSE_CHARS == 75_000


def test_deterministic() -> None:
    def build() -> dict:
        return {
            "memories": [_mem(i, "x" * (1_000 * (i + 1))) for i in range(5)],
        }

    a = bound_payload(build(), [ListTarget("memories")], budget_chars=3_000)
    b = bound_payload(build(), [ListTarget("memories")], budget_chars=3_000)
    assert a == b
