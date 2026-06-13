"""Embedding engine GPU retry and fallback tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


def test_runtime_error_on_gpu_triggers_cpu_fallback():
    engine = EmbeddingEngine(dim=32, device="mps")
    engine._unavailable = False
    mock_model = MagicMock()
    mock_model.encode.side_effect = [
        RuntimeError("MPS backend error"),
        np.random.randn(32).astype(np.float32),
    ]
    mock_model.get_sentence_embedding_dimension.return_value = 32
    engine._model = mock_model

    def fake_ensure():
        engine._model = mock_model

    engine._ensure_model = fake_ensure
    result = engine.encode("test")
    assert result is not None
    assert engine._device == "cpu"


def test_runtime_error_on_cpu_reraises():
    engine = EmbeddingEngine(dim=32, device="cpu")
    engine._device = "cpu"
    engine._unavailable = False
    mock_model = MagicMock()
    mock_model.encode.side_effect = RuntimeError("genuine bug")
    engine._model = mock_model

    with pytest.raises(RuntimeError, match="genuine bug"):
        engine._encode_vec("test")


def test_double_failure_falls_back_to_hash():
    engine = EmbeddingEngine(dim=32, device="cuda")
    engine._unavailable = False
    mock_model = MagicMock()
    mock_model.encode.side_effect = RuntimeError("GPU OOM")
    engine._model = mock_model

    def fake_ensure():
        engine._unavailable = True
        engine._model = None

    engine._ensure_model = fake_ensure
    result = engine.encode("test")
    assert result is not None
    assert len(result) == 32 * 4


def test_cpu_retry_failure_degrades_to_hash():
    engine = EmbeddingEngine(dim=32, device="mps")
    engine._unavailable = False
    mock_model = MagicMock()
    mock_model.encode.side_effect = RuntimeError("bad input")
    mock_model.get_sentence_embedding_dimension.return_value = 32
    engine._model = mock_model

    def fake_ensure():
        engine._model = mock_model

    engine._ensure_model = fake_ensure
    result = engine.encode("test")
    assert result is not None
