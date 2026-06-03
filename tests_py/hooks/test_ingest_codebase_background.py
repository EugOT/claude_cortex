"""Tests for the ingest_codebase_background worker arg handling.

Verifies the ``--reindex`` flag threads through to the handler as
``force_reindex=True`` (the commit-trigger path) and is absent by default
(the SessionStart cached-or-stale path).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_server.hooks import ingest_codebase_background as worker


def _run_with_argv(argv):
    captured = {}

    async def _fake_handler(args):
        captured["args"] = args
        return {"ingested": True, "memories_written": 0}

    fake = AsyncMock(side_effect=_fake_handler)
    with patch("mcp_server.handlers.ingest_codebase.handler", fake):
        with patch.object(worker.sys, "argv", argv):
            with pytest.raises(SystemExit) as exc:
                worker.main()
    return captured.get("args"), exc.value.code


def test_reindex_flag_forces_reindex():
    args, code = _run_with_argv(["ingest_codebase_background", "/proj", "--reindex"])
    assert code == 0
    assert args["project_path"] == "/proj"
    assert args["force_reindex"] is True


def test_no_flag_does_not_force():
    args, code = _run_with_argv(["ingest_codebase_background", "/proj"])
    assert code == 0
    assert args["force_reindex"] is False


def test_missing_project_root_exits_2():
    with patch.object(worker.sys, "argv", ["ingest_codebase_background"]):
        with pytest.raises(SystemExit) as exc:
            worker.main()
    assert exc.value.code == 2
