"""Tests for mcp_server.__main__ entry point."""

import signal
from unittest.mock import patch

import pytest

from mcp_server.__main__ import main, _shutdown, mcp


class TestMain:
    def test_main_is_callable(self):
        assert callable(main)

    def test_main_registers_signal_handlers_and_runs(self):
        with (
            patch("mcp_server.__main__.signal.signal") as mock_signal,
            patch.object(mcp, "run", side_effect=None) as mock_run,
        ):
            main()

            # Should register SIGTERM and SIGINT handlers
            calls = mock_signal.call_args_list
            sig_nums = [c[0][0] for c in calls]
            assert signal.SIGTERM in sig_nums
            assert signal.SIGINT in sig_nums

            # Should call mcp.run with stdio transport
            mock_run.assert_called_once_with(transport="stdio")

    def test_mcp_server_has_tools(self):
        """FastMCP instance should have all 46 tools registered."""
        import asyncio

        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        assert "query_methodology" in tool_names
        assert "detect_domain" in tool_names
        assert "rebuild_profiles" in tool_names
        assert "list_domains" in tool_names
        assert "record_session_end" in tool_names
        # get_methodology_graph / open_visualization / query_workflow_graph
        # were extracted to the cortex-viz MCP.
        assert "get_methodology_graph" not in tool_names
        assert "open_visualization" not in tool_names
        assert "explore_features" in tool_names
        assert "remember" in tool_names
        assert "recall" in tool_names
        assert "memory_stats" in tool_names
        assert "checkpoint" in tool_names
        assert "consolidate" in tool_names
        assert "narrative" in tool_names
        assert "import_sessions" in tool_names
        assert "codebase_analyze" in tool_names
        assert "wiki_write" in tool_names
        assert "wiki_read" in tool_names
        assert "wiki_list" in tool_names
        assert "wiki_link" in tool_names
        assert "wiki_adr" in tool_names
        assert "wiki_reindex" in tool_names
        assert "wiki_purge" in tool_names
        assert "ingest_codebase" in tool_names
        assert "ingest_prd" in tool_names
        # ADR-0046 — automatised-pipeline integration tools.
        assert "wiki_verify" in tool_names
        assert "unified_search" in tool_names
        assert "change_impact" in tool_names
        # query_workflow_graph extracted to cortex-viz MCP.
        assert "query_workflow_graph" not in tool_names
        # Verification campaign — read/write ratio telemetry (Popper C6).
        assert "get_telemetry" in tool_names
        # ADR-2244 Phase 3.2 — page rename with redirect stub.
        assert "wiki_rename" in tool_names
        # 46 tools after the cortex-viz extraction removed 3 visualization
        # tools (get_methodology_graph, open_visualization,
        # query_workflow_graph) from the prior 49.
        assert len(tool_names) == 46

    def test_mcp_server_name_and_version(self):
        assert mcp.name == "methodology-agent"
        assert mcp.version == "1.0.0"

    def test_mcp_server_has_instructions(self):
        assert mcp.instructions is not None
        assert "query_methodology" in mcp.instructions


class TestShutdown:
    def test_shutdown_calls_close_all(self):
        # HTTP viz-server shutdown moved to cortex-viz; _shutdown now only
        # closes the MCP client pool.
        with (
            patch("mcp_server.__main__.close_all") as mock_close,
            pytest.raises(SystemExit) as exc_info,
        ):
            _shutdown()
        mock_close.assert_called_once()
        assert exc_info.value.code == 0

    def test_shutdown_with_signal_args(self):
        with (
            patch("mcp_server.__main__.close_all"),
            pytest.raises(SystemExit),
        ):
            _shutdown(sig=signal.SIGTERM, frame=None)

    def test_shutdown_exits_with_zero(self):
        with (
            patch("mcp_server.__main__.close_all"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _shutdown()
        assert exc_info.value.code == 0
