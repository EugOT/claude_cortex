"""Embedding engine load-failure fallback tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


def test_model_cache_miss_download_failure_degrades_to_hash():
    engine = EmbeddingEngine(dim=32)
    fake_sentence_transformers = SimpleNamespace(
        SentenceTransformer=MagicMock(side_effect=OSError("offline"))
    )

    with patch.dict(
        "sys.modules", {"sentence_transformers": fake_sentence_transformers}
    ):
        result = engine.encode("offline model miss")

    assert result is not None
    assert len(result) == 32 * 4
    assert engine._unavailable is True
    assert fake_sentence_transformers.SentenceTransformer.call_count == 2
