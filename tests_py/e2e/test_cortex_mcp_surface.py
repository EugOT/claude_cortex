"""End-to-end tests for the production Cortex MCP surface.

These tests call the FastMCP server object from ``mcp_server.__main__`` through
``call_tool`` instead of invoking handlers directly. That pins the externally
visible Cortex contract: registration, argument binding, safe-handler behavior,
storage-backed memory tools, and checkpoint restore all work together.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError as PydanticValidationError

from mcp_server.__main__ import mcp


class _DeterministicEmbeddingEngine:
    dimensions = 384

    def encode(self, text: str) -> bytes | None:
        if not text:
            return None
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = (digest * ((self.dimensions // len(digest)) + 1))[: self.dimensions]
        vec = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) + 1.0
        vec = vec / np.linalg.norm(vec)
        return vec.astype(np.float32).tobytes()

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        return [self.encode(text) for text in texts]

    def similarity(self, embedding_a: bytes, embedding_b: bytes) -> float:
        a = np.frombuffer(embedding_a, dtype=np.float32)
        b = np.frombuffer(embedding_b, dtype=np.float32)
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        return 0.0 if denom == 0.0 else float(np.dot(a, b) / denom)

    def to_list(self, embedding: bytes) -> list[float]:
        return np.frombuffer(embedding, dtype=np.float32).tolist()

    def from_list(self, values: list[float]) -> bytes:
        return np.asarray(values, dtype=np.float32).tobytes()


def _run(coro):
    return asyncio.run(coro)


def _call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _run(mcp.call_tool(name, arguments or {}))

    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


@pytest.fixture(autouse=True)
def _deterministic_embeddings(monkeypatch):
    engine = _DeterministicEmbeddingEngine()
    monkeypatch.setattr(
        "mcp_server.handlers.remember.get_embedding_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "mcp_server.handlers.recall.get_embedding_engine",
        lambda: engine,
    )


@pytest.mark.e2e
class TestCortexMcpSurface:
    def test_tool_catalog_exposes_critical_cortex_surface(self):
        tools = _run(mcp.list_tools())
        tool_by_name = {tool.name: tool for tool in tools}

        critical_tools = {
            "query_methodology",
            "detect_domain",
            "remember",
            "recall",
            "memory_stats",
            "checkpoint",
            "consolidate",
            "wiki_write",
            "wiki_read",
            "ingest_codebase",
        }
        assert critical_tools <= set(tool_by_name)

        for name in critical_tools:
            tool = tool_by_name[name]
            assert tool.description
            assert isinstance(tool.parameters, dict)
            assert tool.parameters.get("type") == "object"

    def test_missing_required_tool_argument_fails_before_handler_dispatch(self):
        with pytest.raises(PydanticValidationError, match="Missing required argument"):
            _run(mcp.call_tool("remember", {}))

    def test_oversized_memory_payload_is_rejected_without_traceback(self):
        result = _call_tool(
            "remember",
            {
                "content": "x" * 10001,
                "tags": ["e2e"],
                "domain": "cortex-e2e",
                "force": True,
            },
        )

        assert result["error"] == "ValidationError"
        assert "maximum length" in result["message"]
        serialized = json.dumps(result, default=str)
        assert "Traceback" not in serialized
        assert "File " not in serialized

    def test_remember_recall_stats_and_checkpoint_round_trip(self):
        content = (
            "Cortex e2e sentinel: FastMCP surface tests must cover remember, "
            "recall, stats, and checkpoint restore as one user scenario."
        )

        remember = _call_tool(
            "remember",
            {
                "content": content,
                "tags": ["e2e", "cortex-surface", "scenario-matrix"],
                "directory": "/tmp/cortex-e2e",
                "domain": "cortex-e2e",
                "source": "user",
                "force": True,
            },
        )
        assert remember["stored"] is True
        assert remember["action"] in {"stored", "merged"}
        assert "memory_id" in remember

        stats = _call_tool("memory_stats")
        assert stats["total_memories"] >= 1
        assert isinstance(stats["has_vector_search"], bool)

        recall = _call_tool(
            "recall",
            {
                "query": "FastMCP surface scenario-matrix checkpoint restore",
                "domain": "cortex-e2e",
                "max_results": 5,
                "min_heat": 0.0,
            },
        )
        assert recall["count"] >= 1
        assert any(
            "FastMCP surface tests" in memory["content"]
            for memory in recall["memories"]
        )

        save = _call_tool(
            "checkpoint",
            {
                "action": "save",
                "directory": "/tmp/cortex-e2e",
                "current_task": "Prove the Cortex MCP surface has e2e coverage",
                "files_being_edited": ["tests_py/e2e/test_cortex_mcp_surface.py"],
                "key_decisions": [
                    "Exercise registered tools through FastMCP.call_tool"
                ],
                "next_steps": ["Run mutation testing on the safety wrapper"],
                "session_id": "cortex-e2e-surface",
            },
        )
        assert save["status"] == "saved"
        assert save["checkpoint_id"]

        restore = _call_tool(
            "checkpoint",
            {
                "action": "restore",
                "directory": "/tmp/cortex-e2e",
                "session_id": "cortex-e2e-surface",
            },
        )
        assert restore["status"] == "restored"
        assert restore["checkpoint"] is True
        assert "Cortex MCP surface" in restore["formatted"]
        assert "test_cortex_mcp_surface.py" in restore["formatted"]
