"""Tests for auto_curator — prompt structure + coverage jobs."""

from __future__ import annotations

from mcp_server.core.auto_curator import (
    CurationCluster,
    _ADR_TASK_RECORD_SECTIONS,
    _GENERIC_STRUCTURE_SECTIONS,
    build_authoring_prompt,
    build_coverage_jobs,
    build_coverage_prompt,
    sort_coverage_jobs,
)
from mcp_server.core.wiki_coverage import DomainCoverage, Scope, ScopeCoverage, SCOPES


def _cluster(kind: str = "adr") -> CurationCluster:
    return CurationCluster(
        topic="example-feature",
        domain="cortex",
        suggested_kind=kind,
        suggested_path=f"{kind}/cortex/example-feature.md",
        memory_ids=[1, 2, 3, 4],
        memory_contents=["a" * 200, "b" * 200, "c" * 200, "d" * 200],
        memory_tags=[["x"], ["y"], [], []],
        entities=["FeatureX", "feature_y"],
        avg_heat=0.5,
        earliest_at="2026-05-01",
        latest_at="2026-05-17",
    )


class TestAuthoringPromptKindSpecificSections:
    """The prompt must require Entry/Mandatory/How/Result/Serves for ADRs."""

    def test_adr_prompt_carries_task_record_section_block(self):
        prompt = build_authoring_prompt(_cluster("adr"), related_pages=[])
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
            assert token in prompt, f"ADR prompt missing required section: {token}"

    def test_non_adr_prompt_uses_generic_structure(self):
        prompt = build_authoring_prompt(_cluster("reference"), related_pages=[])
        # Generic structure → no Entry/Mandatory/Result/Serves required.
        assert "## Entry" not in prompt
        assert "## Mandatory elements" not in prompt
        # But it MUST carry the conventional architecture sections.
        assert "Why this design and not the alternatives" in prompt
        assert "What can go wrong" in prompt

    def test_kind_specific_section_constants_distinct(self):
        assert _ADR_TASK_RECORD_SECTIONS != _GENERIC_STRUCTURE_SECTIONS
        assert "Entry" in _ADR_TASK_RECORD_SECTIONS
        assert "Entry" not in _GENERIC_STRUCTURE_SECTIONS


class TestCoveragePrompt:
    def test_coverage_prompt_names_scope_and_path(self):
        prompt = build_coverage_prompt(
            scope_name="architecture",
            scope_title="Architecture overview",
            scope_description="The overall design.",
            suggested_kind="explanation",
            suggested_path="reference/cortex/architecture-overview.md",
            domain="cortex",
            related_pages=["reference/cortex/api.md"],
            supporting_memories=["mem 1 body"],
            supporting_tags=[["arch"]],
            today="2026-05-18",
        )
        assert "architecture" in prompt
        assert "Architecture overview" in prompt
        assert "reference/cortex/architecture-overview.md" in prompt
        assert "cortex" in prompt
        # Cross-link block uses [[wiki/path]] notation.
        assert "[[reference/cortex/api.md]]" in prompt


class TestCoverageJobBuilder:
    def test_emits_one_job_per_missing_scope(self):
        # Domain with 2 missing scopes → 2 jobs.
        missing_arch = ScopeCoverage(
            scope=SCOPES[0],
            domain="cortex",
            covered=False,
            page_count=0,
            anchor_page=None,
            suggested_path="reference/cortex/architecture-overview.md",
        )
        missing_api = ScopeCoverage(
            scope=SCOPES[2],
            domain="cortex",
            covered=False,
            page_count=0,
            anchor_page=None,
            suggested_path="reference/cortex/api.md",
        )
        cov = DomainCoverage(domain="cortex", scopes=[missing_arch, missing_api])
        jobs = build_coverage_jobs([cov])
        assert len(jobs) == 2
        assert {j.scope_name for j in jobs} == {"architecture", "api"}

    def test_sort_by_structural_primacy(self):
        # Mix of architecture, api, data-flow — architecture must come first.
        scopes = [SCOPES[3], SCOPES[2], SCOPES[0]]  # data-flow, api, architecture
        covs = []
        for s in scopes:
            sc = ScopeCoverage(
                scope=s,
                domain="cortex",
                covered=False,
                page_count=0,
                anchor_page=None,
                suggested_path=f"reference/cortex/{s.name}.md",
            )
            covs.append(DomainCoverage(domain="cortex", scopes=[sc]))
        jobs = sort_coverage_jobs(build_coverage_jobs(covs))
        names = [j.scope_name for j in jobs]
        assert names == ["architecture", "api", "data-flow"]
