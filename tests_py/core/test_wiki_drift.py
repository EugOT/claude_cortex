"""Tests for wiki_drift — existing-page re-author detection."""

from __future__ import annotations

import os
import time

from mcp_server.core.wiki_drift import (
    REASON_MISSING_SOURCE,
    REASON_OFF_TEMPLATE,
    REASON_STALE,
    audit_page_drift,
    audit_wiki_drift,
)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


ADR_BODY_WITH_SOURCE = """\
---
title: Foo
kind: adr
updated: 2026-01-01
---

# ADR: Foo

## Status

accepted

## Entry

Used `mcp_server/core/foo.py` to do bar.

## Mandatory elements

- Clean Architecture

## How

Edited `mcp_server/core/foo.py`.

## Result

Done.

## Serves

System.
"""


SHORT_ADR_BODY = """\
---
title: Foo
kind: adr
updated: 2026-04-01
---

# ADR: Foo

Just some prose.
"""


class TestAuditPageDrift:
    def test_no_drift_when_source_exists_and_recent(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        _write(
            str(wiki / "adr" / "p" / "0001-foo.md"), ADR_BODY_WITH_SOURCE
        )
        _write(str(src / "mcp_server" / "core" / "foo.py"), "x")
        # All sections present, source exists, mtime is "now".
        d = audit_page_drift(
            str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365
        )
        assert d is None

    def test_missing_source_file_flagged(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        _write(
            str(wiki / "adr" / "p" / "0001-foo.md"), ADR_BODY_WITH_SOURCE
        )
        # Source root exists but foo.py is missing.
        d = audit_page_drift(
            str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365
        )
        assert d is not None
        assert REASON_MISSING_SOURCE in d.reasons
        assert "mcp_server/core/foo.py" in d.missing_source_files

    def test_stale_when_mtime_old_and_cites_source(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        page = wiki / "adr" / "p" / "0001-foo.md"
        _write(str(page), ADR_BODY_WITH_SOURCE)
        _write(str(src / "mcp_server" / "core" / "foo.py"), "x")
        # Backdate page by 120 days.
        old = time.time() - 120 * 86400
        os.utime(str(page), (old, old))
        d = audit_page_drift(
            str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=60
        )
        assert d is not None
        assert REASON_STALE in d.reasons

    def test_off_template_when_required_sections_missing(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        _write(
            str(wiki / "adr" / "p" / "0001-foo.md"),
            SHORT_ADR_BODY,
        )
        d = audit_page_drift(
            str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365
        )
        assert d is not None
        assert REASON_OFF_TEMPLATE in d.reasons

    def test_no_source_root_skips_missing_check(self, tmp_path):
        """Pages from domains without a checked-out tree don't trigger
        the missing-source-file axis."""
        wiki = tmp_path / "wiki"
        _write(
            str(wiki / "adr" / "_general" / "0001-foo.md"),
            ADR_BODY_WITH_SOURCE,
        )
        d = audit_page_drift(
            str(wiki),
            "adr/_general/0001-foo.md",
            None,
            max_age_days=365,
        )
        # No source root → no missing-source flag. Other reasons may still fire.
        if d is not None:
            assert REASON_MISSING_SOURCE not in d.reasons


class TestAuditWikiDrift:
    def test_walks_every_page(self, tmp_path):
        wiki = tmp_path / "wiki"
        src_a = tmp_path / "a"
        src_b = tmp_path / "b"
        src_a.mkdir()
        src_b.mkdir()
        # Page A: missing source → drifted.
        _write(
            str(wiki / "adr" / "a" / "0001-foo.md"), ADR_BODY_WITH_SOURCE
        )
        # Page B: source exists → clean.
        _write(
            str(wiki / "adr" / "b" / "0001-foo.md"), ADR_BODY_WITH_SOURCE
        )
        _write(str(src_b / "mcp_server" / "core" / "foo.py"), "x")

        def resolver(domain):
            return {"a": str(src_a), "b": str(src_b)}.get(domain)

        drifts = audit_wiki_drift(
            str(wiki), resolver, max_age_days=365
        )
        # Only page A drifts.
        paths = {d.wiki_path for d in drifts}
        assert "adr/a/0001-foo.md" in paths
        assert "adr/b/0001-foo.md" not in paths

    def test_limit_caps_returned(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        for i in range(10):
            _write(
                str(wiki / "adr" / "p" / f"{i:04d}-foo.md"),
                ADR_BODY_WITH_SOURCE,
            )

        def resolver(_):
            return str(src)

        drifts = audit_wiki_drift(
            str(wiki), resolver, max_age_days=365, limit=3
        )
        assert len(drifts) == 3
