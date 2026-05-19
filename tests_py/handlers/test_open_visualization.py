"""Tests for mcp_server.handlers.open_visualization — unified 3D graph launcher."""

import asyncio
from unittest.mock import patch, MagicMock

from mcp_server.handlers import open_visualization
from mcp_server.handlers.open_visualization import handler


class TestOpenVisualizationSchema:
    def test_exports_schema_and_handler(self):
        assert open_visualization.schema is not None
        assert open_visualization.handler is not None
        assert callable(open_visualization.handler)
        assert open_visualization.schema["description"]
        assert open_visualization.schema["inputSchema"]

    def test_domain_is_optional(self):
        required = open_visualization.schema["inputSchema"].get("required", [])
        assert "domain" not in required


class TestOpenVisualizationHandler:
    """The handler now drives the full prepare-then-render pipeline:
    after launching the standalone server it polls /api/graph/progress,
    invokes /api/recompute_layout, and only then opens the browser at
    the ``?viz=tilemap`` path. Tests stub ``_prepare_layout`` so they
    don't issue real HTTP traffic."""

    def test_returns_url(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            result = asyncio.run(handler({}))

        assert result["url"] == "http://localhost:3458/?viz=tilemap"
        assert "localhost" in result["message"]

    def test_default_args_none(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            result = asyncio.run(handler(None))
        assert result["url"] == "http://localhost:3458/?viz=tilemap"

    def test_launches_unified_server_type(self):
        mock_launch = MagicMock(return_value="http://localhost:3458")
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                mock_launch,
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            asyncio.run(handler({}))

        mock_launch.assert_called_once_with("unified")

    def test_opens_browser_at_tilemap_url(self):
        """When extras are present the browser opens at the tilemap URL."""
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.open_in_browser",
            ) as mock_open,
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            asyncio.run(handler({}))
        mock_open.assert_called_once_with("http://localhost:5555/?viz=tilemap")

    def test_opens_browser_at_tilemap_url_unconditionally(self):
        """Handler always opens the tilemap URL — graph build happens on
        demand via the UI's Graph button, not on launch.

        Previously a fallback path opened the legacy URL when
        ``_prepare_layout`` reported ``igraph_missing``; that branch
        was removed when the on-launch layout precomputation was
        dropped (2026-05). The handler now returns immediately after
        opening ``?viz=tilemap`` regardless of any layout state."""
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.open_in_browser",
            ) as mock_open,
        ):
            result = asyncio.run(handler({}))
        mock_open.assert_called_once_with("http://localhost:5555/?viz=tilemap")
        assert "tilemap" in result["message"]
