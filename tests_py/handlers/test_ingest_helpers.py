"""Tests for ingest_helpers graph-path memoisation — the self-heal.

The trust-critical behaviour: a memo whose graph was deleted must NEVER
be handed back to the caller (which would silently project an empty
graph). ``find_cached_graph`` returns only a path whose graph still
exists on disk, preferring the most-recent such memo.

Source: ingest staleness bug Jun-2026 (a memo outlived its graph dir).
"""

from __future__ import annotations

from mcp_server.handlers.ingest_helpers import (
    code_graph_tag,
    find_cached_graph,
    graph_path_is_materialised,
)


class _FakeStore:
    def __init__(self, mems):
        self._mems = mems

    def get_all_memories_for_decay(self):
        return self._mems


class _RaisingStore:
    def get_all_memories_for_decay(self):
        raise RuntimeError("db down")


def _materialised_dir(tmp_path, name="graph"):
    """A graph directory that looks built (non-empty)."""
    d = tmp_path / name
    d.mkdir()
    (d / "data.kz").write_text("x")
    return d


def _memo(tag, path, created_at="2026-06-01T00:00:00", tags_extra=None):
    tags = [tag, "_ingest", "code-graph"]
    if tags_extra:
        tags = tags_extra
    return {
        "content": f"graph_path={path}",
        "tags": tags,
        "created_at": created_at,
    }


PROJECT = "/Users/x/Developments/Demo"


class TestGraphPathIsMaterialised:
    def test_none_and_empty(self):
        assert graph_path_is_materialised(None) is False
        assert graph_path_is_materialised("") is False

    def test_nonexistent_path(self, tmp_path):
        assert graph_path_is_materialised(str(tmp_path / "nope")) is False

    def test_empty_dir_is_invalid(self, tmp_path):
        empty = tmp_path / "graph"
        empty.mkdir()
        assert graph_path_is_materialised(str(empty)) is False

    def test_non_empty_dir_is_valid(self, tmp_path):
        d = _materialised_dir(tmp_path)
        assert graph_path_is_materialised(str(d)) is True

    def test_non_empty_file_is_valid(self, tmp_path):
        f = tmp_path / "graph.ladybug"
        f.write_text("data")
        assert graph_path_is_materialised(str(f)) is True

    def test_empty_file_is_invalid(self, tmp_path):
        f = tmp_path / "graph.ladybug"
        f.write_text("")
        assert graph_path_is_materialised(str(f)) is False


class TestFindCachedGraph:
    def test_no_memos_returns_none(self):
        assert find_cached_graph(_FakeStore([]), PROJECT) is None

    def test_store_error_returns_none(self):
        assert find_cached_graph(_RaisingStore(), PROJECT) is None

    def test_valid_memo_returned(self, tmp_path):
        tag = code_graph_tag(PROJECT)
        d = _materialised_dir(tmp_path)
        store = _FakeStore([_memo(tag, str(d))])
        assert find_cached_graph(store, PROJECT) == str(d)

    def test_dead_memo_returns_none(self, tmp_path):
        """The bug: a memo pointing at a deleted graph is skipped, not
        returned. Caller then re-analyses instead of projecting empty."""
        tag = code_graph_tag(PROJECT)
        store = _FakeStore([_memo(tag, str(tmp_path / "deleted"))])
        assert find_cached_graph(store, PROJECT) is None

    def test_newer_dead_skipped_for_older_valid(self, tmp_path):
        """Self-heal: a newer memo with a dead path must not shadow an
        older memo whose graph still exists."""
        tag = code_graph_tag(PROJECT)
        valid = _materialised_dir(tmp_path)
        store = _FakeStore(
            [
                _memo(tag, str(valid), created_at="2026-06-01T00:00:00"),
                _memo(tag, str(tmp_path / "gone"), created_at="2026-06-09T00:00:00"),
            ]
        )
        assert find_cached_graph(store, PROJECT) == str(valid)

    def test_newest_valid_wins(self, tmp_path):
        tag = code_graph_tag(PROJECT)
        old = _materialised_dir(tmp_path, "old")
        new = _materialised_dir(tmp_path, "new")
        store = _FakeStore(
            [
                _memo(tag, str(old), created_at="2026-06-01T00:00:00"),
                _memo(tag, str(new), created_at="2026-06-09T00:00:00"),
            ]
        )
        assert find_cached_graph(store, PROJECT) == str(new)

    def test_tag_mismatch_ignored(self, tmp_path):
        d = _materialised_dir(tmp_path)
        store = _FakeStore(
            [_memo("_code_graph:other-deadbeef", str(d), tags_extra=["_code_graph:other-deadbeef"])]
        )
        assert find_cached_graph(store, PROJECT) is None

    def test_non_graph_path_content_ignored(self, tmp_path):
        tag = code_graph_tag(PROJECT)
        store = _FakeStore([{"content": "something else", "tags": [tag]}])
        assert find_cached_graph(store, PROJECT) is None

    def test_tags_as_json_string_parsed(self, tmp_path):
        import json

        tag = code_graph_tag(PROJECT)
        d = _materialised_dir(tmp_path)
        store = _FakeStore(
            [{"content": f"graph_path={d}", "tags": json.dumps([tag]), "created_at": ""}]
        )
        assert find_cached_graph(store, PROJECT) == str(d)
