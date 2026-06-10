"""Filesystem-artifact checks for the ~/.claude hygiene doctor.

Split from ``claude_dir_doctor`` along a concern boundary (Move 5):
this module owns the on-disk *binary/snapshot* artifacts (symlinks in
methodology/bin and the viz snapshot), while the doctor owns the
*plugin-registry* artifacts (installed_plugins.json / marketplaces /
cache). Both report through ``[cortex-doctor]`` and never raise.

Path constants are module-level so tests can monkeypatch them.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

_PREFIX = "[cortex-doctor]"

# Module-level paths — monkeypatched by tests against a tmp_path tree.
METHODOLOGY_BIN_DIR = Path.home() / ".claude" / "methodology" / "bin"
VIZ_SNAPSHOT_PATH = Path.home() / ".cache" / "cortex" / "graph-snapshot.bin"


def _emit(line: str) -> None:
    """Write one finding to stderr with the doctor prefix."""
    print(f"{_PREFIX} {line}", file=sys.stderr)


def _plugin_prefix(path: Path) -> str:
    """Family key for a methodology binary: name without version suffix."""
    stem = path.name
    return stem.rsplit("-", 1)[0] if "-" in stem else stem


def _fmt_date(mtime: float) -> str:
    """ISO date for an mtime; bare float on any error."""
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return str(mtime)


def check_symlink_sanity() -> None:
    """Report broken or version-shadowing symlinks in methodology/bin.

    Incident 2026-06-10a: ``mcp-server`` pointed at a June-2 prebuilt
    binary, silently shadowing TWO newer releases (the AP bridge prefers
    that symlink over installed_plugins.json). Report-only: repointing a
    live bridge could break a running process; for a broken link we
    cannot know the correct target.
    """
    if not METHODOLOGY_BIN_DIR.is_dir():
        return
    for entry in sorted(METHODOLOGY_BIN_DIR.iterdir()):
        if not entry.is_symlink():
            continue
        target = entry.resolve()
        if not target.exists():
            _emit(
                f"broken symlink {entry.name} -> {os.readlink(entry)} "
                "(target missing) — re-point manually to a valid binary"
            )
            continue
        _report_shadowing(entry, target)


def _report_shadowing(link: Path, target: Path) -> None:
    """Report when a symlink target is older than a newer sibling binary."""
    family = _plugin_prefix(target)
    target_mtime = target.stat().st_mtime
    newest = target
    newest_mtime = target_mtime
    for sib in METHODOLOGY_BIN_DIR.iterdir():
        if sib.is_symlink() or sib == target or _plugin_prefix(sib) != family:
            continue
        try:
            m = sib.stat().st_mtime
        except OSError:
            continue
        if m > newest_mtime:
            newest, newest_mtime = sib, m
    if newest is not target:
        _emit(
            f"stale binary shadowing newer install: {link.name} -> "
            f"{target.name} ({_fmt_date(target_mtime)}) but newer "
            f"{newest.name} ({_fmt_date(newest_mtime)}) exists"
        )


def check_viz_snapshot() -> None:
    """Delete a provably-empty (0-node) viz snapshot; else report only.

    Incident 2026-06-10c: a stale graph-snapshot.bin with 0 nodes faked
    build readiness (full_ready gated on file size). A 0-node CXGB file
    is provably useless → safe to delete. Unreadable/foreign files are
    reported, not touched.
    """
    path = VIZ_SNAPSHOT_PATH
    if not path.exists():
        return
    try:
        from mcp_server.server.graph_snapshot import peek_counts

        counts = peek_counts(path)
    except Exception as exc:  # import or read failure — never fatal
        _emit(f"viz snapshot unreadable, left in place: {exc}")
        return
    if counts is None:
        _emit(f"viz snapshot not a valid CXGB file, left in place: {path}")
        return
    nodes, _edges = counts
    if nodes == 0:
        try:
            path.unlink()
            _emit(f"deleted empty (0-node) viz snapshot that faked readiness: {path}")
        except OSError as exc:
            _emit(f"empty viz snapshot present but delete failed: {exc}")
