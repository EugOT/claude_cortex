"""Tests for the autonomous consolidate background worker + stamp."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from mcp_server.hooks import consolidate_background


def test_stamp_write_creates_file(tmp_path, monkeypatch):
    target = tmp_path / ".last_consolidate"
    monkeypatch.setattr(consolidate_background, "STAMP_PATH", target)
    consolidate_background._write_stamp()
    assert target.is_file()
    parsed = consolidate_background.read_stamp()
    assert isinstance(parsed, datetime)
    # The freshly-written stamp is within the last 5 seconds.
    assert (datetime.now(timezone.utc) - parsed).total_seconds() < 5


def test_read_stamp_returns_none_when_missing(tmp_path, monkeypatch):
    target = tmp_path / "missing"
    monkeypatch.setattr(consolidate_background, "STAMP_PATH", target)
    assert consolidate_background.read_stamp() is None


def test_read_stamp_returns_none_for_malformed(tmp_path, monkeypatch):
    target = tmp_path / ".last_consolidate"
    target.write_text("not-a-date")
    monkeypatch.setattr(consolidate_background, "STAMP_PATH", target)
    assert consolidate_background.read_stamp() is None


def test_read_stamp_handles_inflight_marker(tmp_path, monkeypatch):
    """The SessionStart writes 'YYYY-...T... (in-flight)' to mark a
    racing spawn. read_stamp tolerates malformed text by returning
    None rather than crashing."""
    target = tmp_path / ".last_consolidate"
    target.write_text("2026-05-18T09:00:00+00:00 (in-flight)")
    monkeypatch.setattr(consolidate_background, "STAMP_PATH", target)
    # fromisoformat rejects the trailing text; read_stamp returns None
    # so the TTL gate treats the worker as "not yet completed" and
    # the next SessionStart will not re-spawn while in-flight (the
    # in-flight marker itself acts as a race guard).
    assert consolidate_background.read_stamp() is None


def test_stamp_round_trip(tmp_path, monkeypatch):
    """Write then read recovers the same instant (to second precision)."""
    target = tmp_path / ".last_consolidate"
    monkeypatch.setattr(consolidate_background, "STAMP_PATH", target)
    consolidate_background._write_stamp()
    written = target.read_text().strip()
    parsed = consolidate_background.read_stamp()
    assert parsed is not None
    assert parsed.isoformat(timespec="seconds") == written
