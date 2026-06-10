"""Tests for the claude_dir_doctor SessionStart hygiene hook.

Each test builds a fake ~/.claude tree under tmp_path and monkeypatches
the module-level path constants. Covers the four checks plus the two
hard invariants: every check survives malformed JSON (no raise) and the
hook always exits 0.

Pre: a tmp_path-rooted fake ~/.claude tree; module path constants
     repointed via monkeypatch.
Post: assertions on stderr findings and on the non-deletion / deletion
      of the viz snapshot; no exception escapes any check.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from mcp_server.hooks import claude_dir_artifacts as artifacts
from mcp_server.hooks import claude_dir_doctor as doctor
from mcp_server.server import graph_snapshot


@pytest.fixture()
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build an empty fake ~/.claude tree and repoint module constants.

    Registry paths live on ``doctor``; binary/snapshot paths live on
    ``artifacts`` after the Move-5 concern split.
    """
    plugins = tmp_path / "plugins"
    monkeypatch.setattr(doctor, "CLAUDE_DIR", tmp_path)
    monkeypatch.setattr(doctor, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(
        doctor, "INSTALLED_PLUGINS_PATH", plugins / "installed_plugins.json"
    )
    monkeypatch.setattr(doctor, "MARKETPLACES_DIR", plugins / "marketplaces")
    monkeypatch.setattr(doctor, "PLUGIN_CACHE_DIR", plugins / "cache")
    monkeypatch.setattr(
        artifacts, "METHODOLOGY_BIN_DIR", tmp_path / "methodology" / "bin"
    )
    monkeypatch.setattr(
        artifacts, "VIZ_SNAPSHOT_PATH", tmp_path / "cache" / "graph-snapshot.bin"
    )
    return tmp_path


def _write_installed(root: Path, name: str, marketplace: str, version: str) -> None:
    path = root / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "plugins": {f"{name}@{marketplace}": [{"scope": "user", "version": version}]},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_marketplace(root: Path, marketplace: str, name: str, version: str) -> None:
    path = (
        root
        / "plugins"
        / "marketplaces"
        / marketplace
        / ".claude-plugin"
        / "marketplace.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": marketplace,
        "metadata": {"version": version},
        "plugins": [{"name": name, "version": version}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_snapshot(path: Path, nodes: int, edges: int) -> None:
    """Write a minimal valid CXGB header with the given counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = struct.pack(
        graph_snapshot._HEADER_FMT,
        graph_snapshot.MAGIC,
        graph_snapshot.VERSION,
        0,
        nodes,
        edges,
        0,
        0,
        0,
    )
    path.write_bytes(head)


# --- Check 1: plugin freshness -------------------------------------------


def test_outdated_plugin_detected(fake_claude, capsys):
    _write_installed(fake_claude, "cortex", "cortex-mkt", "0.3.0")
    _write_marketplace(fake_claude, "cortex-mkt", "cortex", "0.4.0")

    doctor.check_plugin_freshness()

    err = capsys.readouterr().err
    assert "plugin cortex 0.3.0 < marketplace 0.4.0" in err
    assert "claude plugin update cortex@cortex-mkt" in err


def test_up_to_date_plugin_is_silent(fake_claude, capsys):
    _write_installed(fake_claude, "cortex", "cortex-mkt", "0.4.0")
    _write_marketplace(fake_claude, "cortex-mkt", "cortex", "0.4.0")

    doctor.check_plugin_freshness()

    assert capsys.readouterr().err == ""


def test_unparseable_version_does_not_crash(fake_claude, capsys):
    _write_installed(fake_claude, "cortex", "cortex-mkt", "garbage")
    _write_marketplace(fake_claude, "cortex-mkt", "cortex", "0.4.0")

    doctor.check_plugin_freshness()  # must not raise

    assert capsys.readouterr().err == ""


# --- Check 2: symlink sanity ---------------------------------------------


def test_broken_symlink_reported(fake_claude, capsys):
    bin_dir = fake_claude / "methodology" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "mcp-server").symlink_to(bin_dir / "does-not-exist")

    artifacts.check_symlink_sanity()

    err = capsys.readouterr().err
    assert "broken symlink mcp-server" in err
    assert "target missing" in err


def test_stale_binary_shadowing_reported(fake_claude, capsys):
    import os
    import time

    bin_dir = fake_claude / "methodology" / "bin"
    bin_dir.mkdir(parents=True)
    old = bin_dir / "automatised-pipeline-0.3.0"
    new = bin_dir / "automatised-pipeline-0.4.0"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    now = time.time()
    os.utime(old, (now - 1000, now - 1000))
    os.utime(new, (now, now))
    (bin_dir / "mcp-server").symlink_to(old)

    artifacts.check_symlink_sanity()

    err = capsys.readouterr().err
    assert "stale binary shadowing newer install" in err
    assert "automatised-pipeline-0.4.0" in err


# --- Check 3: stale cache versions ---------------------------------------


def test_stale_cache_versions_reported(fake_claude, capsys):
    _write_installed(fake_claude, "ap", "ap-mkt", "0.4.0")
    cache = fake_claude / "plugins" / "cache" / "ap-mkt" / "ap"
    for ver in ("0.2.2", "0.3.0", "0.4.0"):
        (cache / ver).mkdir(parents=True)
        (cache / ver / "blob").write_bytes(b"x" * 2048)

    doctor.check_stale_cache_versions()

    err = capsys.readouterr().err
    assert "2 stale cached plugin version(s)" in err
    assert "claude plugin prune" in err


# --- Check 4: viz snapshot -----------------------------------------------


def test_empty_snapshot_deleted(fake_claude, capsys):
    snap = fake_claude / "cache" / "graph-snapshot.bin"
    _write_snapshot(snap, nodes=0, edges=0)

    artifacts.check_viz_snapshot()

    assert not snap.exists()
    assert "deleted empty (0-node) viz snapshot" in capsys.readouterr().err


def test_valid_snapshot_untouched(fake_claude, capsys):
    snap = fake_claude / "cache" / "graph-snapshot.bin"
    _write_snapshot(snap, nodes=42, edges=10)

    artifacts.check_viz_snapshot()

    assert snap.exists()
    assert capsys.readouterr().err == ""


def test_foreign_snapshot_reported_not_deleted(fake_claude, capsys):
    snap = fake_claude / "cache" / "graph-snapshot.bin"
    snap.parent.mkdir(parents=True)
    snap.write_bytes(b"not a cxgb file at all")

    artifacts.check_viz_snapshot()

    assert snap.exists()
    assert "not a valid CXGB file" in capsys.readouterr().err


# --- Robustness invariants -----------------------------------------------


def test_every_check_survives_malformed_json(fake_claude, capsys):
    (fake_claude / "plugins").mkdir(parents=True)
    (fake_claude / "plugins" / "installed_plugins.json").write_text(
        "{not json", encoding="utf-8"
    )
    mkt = fake_claude / "plugins" / "marketplaces" / "m" / ".claude-plugin"
    mkt.mkdir(parents=True)
    (mkt / "marketplace.json").write_text("}}bad", encoding="utf-8")

    doctor.run_all_checks()  # must not raise

    # No traceback / no "skipped (non-fatal)" — malformed JSON is tolerated.
    assert "skipped (non-fatal)" not in capsys.readouterr().err


def test_hook_never_exits_nonzero(fake_claude):
    with pytest.raises(SystemExit) as exc:
        doctor.main()
    assert exc.value.code == 0
