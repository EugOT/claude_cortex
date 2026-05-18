"""Tests for auto_task_record — session-end ADR drafting."""

from __future__ import annotations

from mcp_server.core.auto_task_record import (
    TaskRecordInputs,
    build_task_record,
    is_substantive,
)


def _inputs(**kw) -> TaskRecordInputs:
    base = dict(
        session_id="sess-42",
        domain="cortex",
        cwd="/Users/x/Cortex",
        duration_seconds=900.0,
        turn_count=12,
        commits=[],
        memories=[],
        changed_files=[],
        tools_used=[],
    )
    base.update(kw)
    return TaskRecordInputs(**base)


class TestSubstantive:
    def test_session_with_one_commit_is_substantive(self):
        i = _inputs(commits=[{"hash": "abc", "message": "fix"}])
        assert is_substantive(i) is True

    def test_session_with_only_two_memories_not_substantive(self):
        i = _inputs(memories=[{"content": "x"}, {"content": "y"}])
        assert is_substantive(i) is False  # needs 5+ tools too

    def test_session_with_memories_and_many_tools_is_substantive(self):
        i = _inputs(
            memories=[{"content": "x"}, {"content": "y"}],
            tools_used=["Read", "Edit", "Bash", "Grep", "Write"],
        )
        assert is_substantive(i) is True

    def test_empty_session_not_substantive(self):
        assert is_substantive(_inputs()) is False


class TestBuildTaskRecord:
    def test_path_uses_domain_and_adr_number(self):
        r = build_task_record(
            _inputs(commits=[{"hash": "abc", "message": "fix login bug"}]),
            adr_number=42,
        )
        assert r.suggested_path.startswith("adr/cortex/0042-")
        assert r.suggested_path.endswith(".md")

    def test_title_derived_from_first_commit_subject(self):
        r = build_task_record(
            _inputs(
                commits=[{"hash": "h1", "message": "feat(wiki): autonomous purge"}]
            ),
            adr_number=1,
        )
        assert "autonomous purge" in r.title
        assert r.frontmatter["title"].startswith("feat(wiki)")

    def test_body_carries_every_mandatory_section(self):
        r = build_task_record(
            _inputs(
                commits=[{"hash": "h1", "message": "fix"}],
                changed_files=["a.py", "b.py"],
            ),
            adr_number=1,
        )
        for token in (
            "## Status",
            "## Entry",
            "## Mandatory elements",
            "## How",
            "## Result",
            "## Serves",
            "## Alternatives considered",
            "## References",
        ):
            assert token in r.body, f"task-record missing section: {token}"

    def test_frontmatter_marks_draft_provenance(self):
        r = build_task_record(
            _inputs(commits=[{"hash": "h", "message": "x"}]),
            adr_number=1,
        )
        assert r.frontmatter["lifecycle"] == "draft"
        assert r.frontmatter["provenance"] == "auto-generated"
        assert r.frontmatter["status"] == "proposed"

    def test_how_section_lists_commits_and_files(self):
        r = build_task_record(
            _inputs(
                commits=[
                    {"hash": "abcdef1234", "message": "first"},
                    {"hash": "ghijkl5678", "message": "second"},
                ],
                changed_files=["mcp_server/core/foo.py"],
            ),
            adr_number=1,
        )
        assert "abcdef12" in r.body  # short hash
        assert "first" in r.body
        assert "second" in r.body
        assert "mcp_server/core/foo.py" in r.body
