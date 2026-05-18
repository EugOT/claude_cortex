"""Curation-gap detector for file-doc pages.

User direction 2026-05-18: *"Removing is not a solution, fixing the
curation by showing information that should be present and missing for
each file is a curation of the documentation."*

This module is the operationalisation of that policy. Given a wiki
page (typically a per-source-file reference), it identifies which
sections SHOULD be present for a real curated explanation and which
are absent. The list of missing sections is:

  1. Embedded in the page frontmatter as ``curation_gaps: [...]``.
  2. Rendered prominently at the top of the page by the wiki view.
  3. Queued as re-author jobs by the auto-curator so the in-session
     LLM fills the gaps over time.

Nothing here deletes content. Pages with gaps stay on disk; the gaps
are surfaced so the reader knows what's coming and the author knows
what to write.

Pure logic — no I/O. Callers pass body text + frontmatter dict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


# ── Section catalogue for a file-doc page ──────────────────────────
#
# Every file-doc page should answer these questions. Each entry has:
#   - ``name`` — slug used in frontmatter ``curation_gaps``.
#   - ``heading`` — the H2 the LLM should write under.
#   - ``probes`` — patterns that, if present in the body, signal the
#     section is covered. A page satisfies the section when at least
#     one probe hits — usually the heading itself plus content under it.
#   - ``min_chars_under_heading`` — extra signal: a heading present
#     but with under N chars of prose under it doesn't count as
#     covered (it's a placeholder skeleton).
#   - ``description`` — what the LLM should write under this heading.


@dataclass(frozen=True)
class CurationSection:
    name: str
    heading: str
    probes: tuple[str, ...]
    min_chars_under_heading: int
    description: str


# Sections every file-doc must cover. The list is deliberately stable —
# adding/removing a section is a deliberate policy edit, not an emergent
# property of the audit.
FILE_DOC_SECTIONS: Final[tuple[CurationSection, ...]] = (
    CurationSection(
        name="purpose",
        heading="## Purpose",
        probes=("## Purpose", "## What this file does"),
        min_chars_under_heading=200,
        description=(
            "What this file is responsible for, in two to four sentences. "
            "Not a restatement of the filename — what behaviour it owns, "
            "what it must NOT do, where its boundary lies."
        ),
    ),
    CurationSection(
        name="public-api",
        heading="## Public API",
        probes=("## Public API", "## API", "## Exports"),
        min_chars_under_heading=150,
        description=(
            "Each exported symbol (function, class, constant) with a "
            "one-line semantic — what it does, what it returns, when "
            "to call it. NOT a bare list of names."
        ),
    ),
    CurationSection(
        name="dependencies",
        heading="## Dependencies",
        probes=("## Dependencies", "## Imports", "## Uses"),
        min_chars_under_heading=80,
        description=(
            "Why each import is here. 'json' is uninteresting; "
            "'sentence_transformers' (the embedding model) is. "
            "Group standard-library imports separately."
        ),
    ),
    CurationSection(
        name="callers",
        heading="## Callers",
        probes=("## Callers", "## Used by", "## Consumers"),
        min_chars_under_heading=100,
        description=(
            "Which files in the project depend on this one. The author "
            "should grep the repo for imports of this module and list "
            "the top callers with one-line context."
        ),
    ),
    CurationSection(
        name="behaviour",
        heading="## How it works",
        probes=("## How it works", "## Behaviour", "## Behavior", "## Implementation"),
        min_chars_under_heading=400,
        description=(
            "Walk through the file's main flow: entry point, key "
            "branches, state transitions. Diagram (mermaid) preferred "
            "for anything sequence-shaped."
        ),
    ),
    CurationSection(
        name="invariants",
        heading="## Invariants",
        probes=("## Invariants", "## Constraints", "## Contracts"),
        min_chars_under_heading=80,
        description=(
            "What must always be true about this file's outputs / "
            "internal state. Layer-boundary contracts, type guarantees, "
            "thread-safety, idempotency. Empty 'none' is fine when "
            "truly none — say so explicitly."
        ),
    ),
    CurationSection(
        name="failure-modes",
        heading="## What can go wrong",
        probes=("## What can go wrong", "## Failure modes", "## Errors"),
        min_chars_under_heading=120,
        description=(
            "How this file can fail in production and what the symptom "
            "looks like. The reader should be able to recognise the "
            "failure from a stack trace or log line."
        ),
    ),
    CurationSection(
        name="tests",
        heading="## Tests",
        probes=("## Tests", "## Test coverage", "## Testing"),
        min_chars_under_heading=80,
        description=(
            "Which test files exercise this file. Path + brief on what "
            "each test covers."
        ),
    ),
    CurationSection(
        name="sequence-diagram",
        heading="## Sequence diagram",
        probes=(
            "## Sequence diagram",
            "## Flow diagram",
            "## Sequence",
            "```mermaid\nsequenceDiagram",
        ),
        min_chars_under_heading=120,
        description=(
            "A `mermaid` sequence diagram of the typical call flow "
            "involving this file — caller → this file → callees → "
            "return. Render with ```mermaid sequenceDiagram fences. "
            "For files that participate in no sequence (pure data "
            'types, constants), explicitly write "Not applicable — '
            'this file participates in no sequence flow" and explain '
            "why."
        ),
    ),
    CurationSection(
        name="parameters",
        heading="## Parameters",
        probes=("## Parameters", "## Arguments", "## Options"),
        min_chars_under_heading=120,
        description=(
            "Exhaustive table of every parameter exposed by this "
            "file's public entry points. Columns: name | type | "
            "required | default | description. For files with no "
            "external parameter surface (internal helpers, pure "
            'data), write "Not applicable — this file exposes no '
            'external parameters."'
        ),
    ),
    CurationSection(
        name="request-example",
        heading="## Request example",
        probes=(
            "## Request example",
            "## Example request",
            "## Request",
            "## Invocation example",
        ),
        min_chars_under_heading=120,
        description=(
            "A concrete request example — for HTTP handlers, the "
            "full curl command including headers (Content-Type, "
            "Authorization, custom headers); for MCP tools, the "
            "JSON-RPC envelope with `method` and `params`; for "
            "library functions, the call site as it would appear "
            "in client code. Show headers explicitly — never omit "
            "them. For files that don't sit on a request boundary, "
            'write "Not applicable — this file is not invoked '
            'directly by callers; see [[Callers]] for the call chain."'
        ),
    ),
    CurationSection(
        name="response-example",
        heading="## Response example",
        probes=(
            "## Response example",
            "## Example response",
            "## Response",
            "## Return value",
        ),
        min_chars_under_heading=120,
        description=(
            "A concrete response example showing every field the "
            "caller receives — JSON for HTTP / MCP, return-value "
            "structure for library functions. Each non-obvious "
            "field annotated with one line explaining what it "
            "means. Include both success and the most common "
            "error shape if applicable. For files that produce "
            'no response surface, write "Not applicable — this '
            'file does not produce a response artifact."'
        ),
    ),
)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _section_body(body: str, heading: str) -> str | None:
    """Return the prose under ``heading`` (up to the next H2+) or None."""
    target = heading.strip()
    lines = body.splitlines()
    in_section = False
    out: list[str] = []
    target_depth: int | None = None
    for ln in lines:
        m = _HEADING_RE.match(ln)
        if m:
            depth = len(m.group(1))
            text = ("#" * depth) + " " + m.group(2).strip()
            if text == target:
                in_section = True
                target_depth = depth
                continue
            if in_section and depth <= (target_depth or 99):
                break
        if in_section:
            out.append(ln)
    if not in_section:
        return None
    return "\n".join(out).strip()


def _meaningful_chars(text: str) -> int:
    """Count chars of real prose (skip blank lines, bullets, fences)."""
    count = 0
    in_fence = False
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith(("#", "-", "*", "+")):
            continue
        count += len(s)
    return count


def missing_sections(body: str) -> list[CurationSection]:
    """Return the canonical sections this file-doc is missing.

    A section is considered missing when EITHER:
      * No probe heading appears in the body, OR
      * A probe heading appears but has fewer than its
        ``min_chars_under_heading`` of prose under it.
    """
    out: list[CurationSection] = []
    for section in FILE_DOC_SECTIONS:
        found = False
        for probe in section.probes:
            sec_body = _section_body(body, probe)
            if sec_body is None:
                continue
            found = True
            if _meaningful_chars(sec_body) >= section.min_chars_under_heading:
                # Section present AND substantive.
                found = True
                break
            # Heading exists but body is too thin — count as missing.
            found = False
        if not found:
            out.append(section)
    return out


def gap_report(body: str) -> dict:
    """Return a structured gap report for embedding in frontmatter and UI.

    Shape:
        {
          "complete": False,
          "missing": ["purpose", "public-api", ...],
          "missing_titles": ["## Purpose — What this file does", ...],
          "completion_pct": 0.25,
        }
    """
    missing = missing_sections(body)
    total = len(FILE_DOC_SECTIONS)
    return {
        "complete": not missing,
        "missing": [s.name for s in missing],
        "missing_titles": [s.heading for s in missing],
        "missing_descriptions": [s.description for s in missing],
        "completion_pct": round((total - len(missing)) / total, 2) if total else 1.0,
        "total_sections": total,
        "covered_sections": total - len(missing),
    }


def render_gap_banner(gap: dict) -> str:
    """Render a Markdown banner the wiki view shows above the page body.

    The banner lists every missing section with its description so the
    reader sees concretely what's not yet written and the LLM (or human
    author) knows exactly what to add next. Empty string when the page
    is complete.
    """
    if gap.get("complete"):
        return ""
    missing = gap.get("missing") or []
    titles = gap.get("missing_titles") or []
    descs = gap.get("missing_descriptions") or []
    if not missing:
        return ""
    lines: list[str] = []
    pct = int((gap.get("completion_pct") or 0) * 100)
    lines.append(
        f"> ⚠ **This page is {pct}% curated.** {len(missing)} sections are "
        "missing or too thin to count. The autonomous re-author loop "
        "will fill them, or you can author them now — what's needed:"
    )
    lines.append(">")
    for i, name in enumerate(missing):
        title = titles[i] if i < len(titles) else f"## {name}"
        desc = descs[i] if i < len(descs) else ""
        lines.append(f"> * **{title.lstrip('# ').strip()}** — {desc}")
    return "\n".join(lines) + "\n"
