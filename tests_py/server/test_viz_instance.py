"""Tests for mcp_server.server.viz_instance — single-instance registry.

The registry exists to stop ``open_visualization`` from leaking one
server per call: reuse a live instance running current code, discover
instances that bound an ephemeral port, and kill-and-WAIT before
respawning (the no-wait kill was the bind race that caused the
ephemeral-port fallback in the first place).
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from mcp_server.server import viz_instance


def _patch_registry(tmp_path: Path):
    return patch.object(
        viz_instance, "instance_path", lambda: tmp_path / "viz-server.json"
    )


class TestRegistryRoundTrip:
    def test_write_then_read(self, tmp_path):
        with _patch_registry(tmp_path):
            viz_instance.write_instance(56746)
            inst = viz_instance.read_instance()
        assert inst is not None
        assert inst["pid"] == os.getpid()
        assert inst["port"] == 56746
        assert inst["started_at"] <= time.time()

    def test_missing_file_reads_none(self, tmp_path):
        with _patch_registry(tmp_path):
            assert viz_instance.read_instance() is None

    def test_corrupt_file_reads_none(self, tmp_path):
        (tmp_path / "viz-server.json").write_text("{not json")
        with _patch_registry(tmp_path):
            assert viz_instance.read_instance() is None

    def test_dead_pid_invalidates_registry(self, tmp_path):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        (tmp_path / "viz-server.json").write_text(
            f'{{"pid": {proc.pid}, "port": 3458, "started_at": 1.0}}'
        )
        with _patch_registry(tmp_path):
            assert viz_instance.read_instance() is None


class TestFreshness:
    def test_newest_source_mtime_ignores_pycache(self, tmp_path):
        src = tmp_path / "mcp_server"
        (src / "__pycache__").mkdir(parents=True)
        code = src / "mod.py"
        code.write_text("x = 1")
        os.utime(code, (1_000.0, 1_000.0))
        pyc = src / "__pycache__" / "mod.cpython-312.pyc"
        pyc.write_bytes(b"\x00")
        # Bytecode is refreshed by merely RUNNING the server — it must
        # not mark the running server stale against its own source.
        os.utime(pyc, (2_000_000_000.0, 2_000_000_000.0))
        assert viz_instance.newest_source_mtime(tmp_path) == 1_000.0

    def test_is_current_true_when_started_after_last_edit(self, tmp_path):
        src = tmp_path / "ui"
        src.mkdir()
        f = src / "viz.html"
        f.write_text("<html/>")
        os.utime(f, (1_000.0, 1_000.0))
        assert viz_instance.is_current({"started_at": 1_001.0}, tmp_path)
        assert not viz_instance.is_current({"started_at": 999.0}, tmp_path)

    def test_is_current_false_on_malformed_instance(self, tmp_path):
        assert not viz_instance.is_current({}, tmp_path)
        assert not viz_instance.is_current({"started_at": "nan?"}, tmp_path)


class TestReusableInstance:
    def test_none_without_registry(self, tmp_path):
        with _patch_registry(tmp_path):
            assert viz_instance.reusable_instance(None) is None

    def test_none_when_probe_fails(self, tmp_path):
        with (
            _patch_registry(tmp_path),
            patch.object(viz_instance, "probe", return_value=False),
        ):
            viz_instance.write_instance(56746)
            assert viz_instance.reusable_instance(None) is None

    def test_reused_when_alive_and_current(self, tmp_path):
        src = tmp_path / "mcp_server"
        src.mkdir()
        f = src / "mod.py"
        f.write_text("x = 1")
        os.utime(f, (1_000.0, 1_000.0))
        with (
            _patch_registry(tmp_path),
            patch.object(viz_instance, "probe", return_value=True),
        ):
            viz_instance.write_instance(56746)  # started_at = now >> 1000
            inst = viz_instance.reusable_instance(tmp_path)
        assert inst is not None and inst["port"] == 56746

    def test_stale_code_forces_respawn(self, tmp_path):
        src = tmp_path / "mcp_server"
        src.mkdir()
        f = src / "mod.py"
        f.write_text("x = 1")
        # Source edited FAR in the future relative to server start.
        os.utime(f, (time.time() + 10_000, time.time() + 10_000))
        with (
            _patch_registry(tmp_path),
            patch.object(viz_instance, "probe", return_value=True),
        ):
            viz_instance.write_instance(56746)
            assert viz_instance.reusable_instance(tmp_path) is None

    def test_no_src_root_skips_freshness_check(self, tmp_path):
        with (
            _patch_registry(tmp_path),
            patch.object(viz_instance, "probe", return_value=True),
        ):
            viz_instance.write_instance(56746)
            assert viz_instance.reusable_instance(None) is not None


class TestKillAndWait:
    def test_kills_live_process_and_waits(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            assert viz_instance.kill_and_wait(proc.pid, timeout=5.0)
            # The pid must be gone — the whole point is no bind race.
            proc.wait(timeout=1)
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_already_dead_pid_returns_true(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        assert viz_instance.kill_and_wait(proc.pid)
