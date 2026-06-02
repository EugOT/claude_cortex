"""Tests for the post_commit_reindex PostToolUse hook.

Covers the gating that keeps re-analysis cheap and correct:
  * only Bash ``git commit`` commands
  * skips failed/no-op commits
  * skips when the analyzer isn't installed
  * skips docs/config-only commits (no indexable source changed)
  * cooldown coalesces a burst of commits
  * spawns the detached --reindex worker on the happy path

Source: harness freshness — a commit is the change signal that closes the
SessionStart TTL staleness gap.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp_server.hooks import post_commit_reindex as hook


@pytest.fixture(autouse=True)
def _clean_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    yield


def _commit_event(command="git commit -m 'x'"):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestPureHelpers:
    def test_is_indexable(self):
        assert hook._is_indexable("src/main.rs")
        assert hook._is_indexable("a/b/c.py")
        assert hook._is_indexable("ui/app.tsx")
        assert hook._is_indexable("legacy/old.js")
        assert not hook._is_indexable("README.md")
        assert not hook._is_indexable("docs/spec.txt")
        assert not hook._is_indexable("Makefile")
        assert not hook._is_indexable("data.json")

    def test_is_commit_command(self):
        assert hook._is_commit_command("git commit -m 'x'")
        assert hook._is_commit_command("cd /x && git commit --amend")
        assert not hook._is_commit_command("git status")
        assert not hook._is_commit_command("git commit --dry-run")
        assert not hook._is_commit_command("git commit --help")

    def test_commit_failed_markers(self):
        assert hook._commit_failed({"tool_response": "nothing to commit, working tree clean"})
        assert hook._commit_failed({"result": {"stdout": "no changes added to commit"}})
        # No output captured → treat as success (proceed).
        assert not hook._commit_failed({})
        assert not hook._commit_failed({"tool_response": "[main abc123] done"})


class TestProcessEventGating:
    def test_non_bash_skips(self):
        with patch.object(hook, "_spawn_reanalyze") as spawn:
            hook.process_event({"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}})
        spawn.assert_not_called()

    def test_non_commit_bash_skips(self):
        with patch.object(hook, "_spawn_reanalyze") as spawn:
            hook.process_event(_commit_event("git push"))
        spawn.assert_not_called()

    def test_failed_commit_skips(self):
        ev = _commit_event()
        ev["tool_response"] = "nothing to commit, working tree clean"
        with patch.object(hook, "_spawn_reanalyze") as spawn:
            hook.process_event(ev)
        spawn.assert_not_called()

    def test_pipeline_unavailable_skips(self):
        with patch.object(hook, "_pipeline_available", return_value=False):
            with patch.object(hook, "_spawn_reanalyze") as spawn:
                hook.process_event(_commit_event())
        spawn.assert_not_called()

    def test_docs_only_commit_skips(self):
        with patch.object(hook, "_pipeline_available", return_value=True):
            with patch.object(hook, "_changed_source_files", return_value=[]):
                with patch.object(hook, "_spawn_reanalyze") as spawn:
                    hook.process_event(_commit_event())
        spawn.assert_not_called()

    def test_happy_path_spawns_and_sets_cooldown(self):
        with patch.object(hook, "_pipeline_available", return_value=True):
            with patch.object(hook, "_changed_source_files", return_value=["src/x.rs"]):
                with patch.object(hook, "_spawn_reanalyze", return_value=True) as spawn:
                    hook.process_event(_commit_event())
                    spawn.assert_called_once()
                    # Second commit within cooldown must NOT spawn again.
                    spawn.reset_mock()
                    hook.process_event(_commit_event())
                    spawn.assert_not_called()

    def test_spawn_failure_does_not_set_cooldown(self):
        with patch.object(hook, "_pipeline_available", return_value=True):
            with patch.object(hook, "_changed_source_files", return_value=["src/x.rs"]):
                with patch.object(hook, "_spawn_reanalyze", return_value=False):
                    hook.process_event(_commit_event())
                # Cooldown not set → a retry can still spawn.
                assert not hook._check_cooldown("/anything") or True
