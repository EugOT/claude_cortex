"""Tests for deterministic gist extraction (core, pure logic)."""

from __future__ import annotations

from mcp_server.core.gist_extraction import (
    GIST_BUDGET,
    extract_gist,
    needs_gist,
)

# Two elision markers' worth of fixed overhead is the documented allowance.
_OVERHEAD = 200


def test_needs_gist_threshold():
    assert needs_gist("x" * (GIST_BUDGET + 1)) is True
    assert needs_gist("x" * GIST_BUDGET) is False
    assert needs_gist("") is False


def test_small_output_passthrough():
    small = "line one\nline two\nline three"
    assert extract_gist(small) == small


def test_gist_respects_budget():
    big = "\n".join(f"filler line number {i} padding padding" for i in range(2000))
    gist = extract_gist(big)
    assert len(gist) <= GIST_BUDGET + _OVERHEAD


def test_signal_line_beyond_head_window_survives():
    # Bury a unique error line deep in the dump, far past the head window.
    filler = "\n".join(f"ordinary filler line {i}" for i in range(2000))
    marker = "FATAL: traceback exception occurred in payment handler"
    big = filler[:GIST_BUDGET] + "\n" + marker + "\n" + filler
    gist = extract_gist(big)
    assert marker in gist


def test_elision_marker_present():
    big = "\n".join(f"line {i} content here" for i in range(2000))
    gist = extract_gist(big)
    assert "[gist:" in gist and "full output in artifact" in gist


def test_deterministic():
    big = "\n".join(f"line {i} with some error text" for i in range(2000))
    assert extract_gist(big) == extract_gist(big)


def test_never_exceeds_budget_overhead_no_newlines():
    # A single huge line with no newlines: head/tail fill is line-granular,
    # so the gist must still stay bounded and never raise.
    big = "x" * (GIST_BUDGET * 4)
    gist = extract_gist(big)
    assert len(gist) <= GIST_BUDGET + _OVERHEAD


def test_custom_budget():
    big = "\n".join(f"line {i}" for i in range(500))
    gist = extract_gist(big, budget=300)
    assert len(gist) <= 300 + _OVERHEAD
