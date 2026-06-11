"""Wiring test: hierarchical write-gate score path (default-off flag).

Verifies the hierarchical novelty scorer is on the same [0,1] scale as the
flat path and that the settings flag defaults to flat (no behaviour change
until an A/B proves the hierarchical path regression-free).
"""

from __future__ import annotations

from mcp_server.handlers.remember_helpers import _hierarchical_novelty_score
from mcp_server.infrastructure.memory_config import get_memory_settings


def test_flag_defaults_to_flat():
    # Default must stay flat so the production write path is unchanged
    # until benchmarks justify flipping it.
    assert get_memory_settings().WRITE_GATE_HIERARCHICAL is False


def test_hierarchical_score_in_unit_interval():
    recent = [{"content": "Fixed the CI deadlock in the asyncio reader loop."}]
    score = _hierarchical_novelty_score(
        content="A completely new topic about quantum error correction codes.",
        ent_names=["quantum error correction"],
        known=set(),
        recent=recent,
    )
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_hierarchical_score_handles_empty_recent():
    # No recent memories -> default sensory predictions, still a valid score.
    score = _hierarchical_novelty_score(
        content="Some content.", ent_names=[], known=set(), recent=[]
    )
    assert 0.0 <= score <= 1.0


def test_novel_scores_at_least_as_high_as_familiar():
    recent = [{"content": "deploy notes deploy notes deploy notes"}]
    novel = _hierarchical_novelty_score(
        content="```python\nimport torch\n```\nfile.py:1 https://x.io\n# H\n- a\n- b",
        ent_names=["torch"],
        known=set(),
        recent=recent,
    )
    familiar = _hierarchical_novelty_score(
        content="deploy notes deploy notes deploy notes",
        ent_names=[],
        known=set(),
        recent=recent,
    )
    assert novel >= familiar
