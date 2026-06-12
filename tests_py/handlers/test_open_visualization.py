"""Tests for mcp_server.handlers.open_visualization — unified 3D graph launcher."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from mcp_server.handlers import open_visualization
from mcp_server.handlers.open_visualization import (
    _find_dev_source,
    _url_from_bootstrap,
    handler,
)


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
    """The handler delegates to the bootstrap script when a dev source
    exists, otherwise to ``launch_server``. Tests stub
    ``_find_dev_source`` to ``None`` so they are hermetic on developer
    machines (a real checkout at ``~/Developments/Cortex`` would
    otherwise run the real bootstrap subprocess and kill live
    servers), and exercise the ``launch_server`` fallback path."""

    def test_returns_url(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization._find_dev_source",
                return_value=None,
            ),
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            result = asyncio.run(handler({}))

        assert result["url"] == "http://localhost:3458/?viz=force"
        assert "localhost" in result["message"]

    def test_default_args_none(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization._find_dev_source",
                return_value=None,
            ),
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            result = asyncio.run(handler(None))
        assert result["url"] == "http://localhost:3458/?viz=force"

    def test_launches_unified_server_type(self):
        mock_launch = MagicMock(return_value="http://localhost:3458")
        with (
            patch(
                "mcp_server.handlers.open_visualization._find_dev_source",
                return_value=None,
            ),
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                mock_launch,
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            asyncio.run(handler({}))

        mock_launch.assert_called_once_with("unified")

    def test_opens_browser_at_force_url_unconditionally(self):
        """Handler always opens the force-directed URL — graph build happens on
        demand via the UI's Graph button, not on launch."""
        with (
            patch(
                "mcp_server.handlers.open_visualization._find_dev_source",
                return_value=None,
            ),
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.open_in_browser",
            ) as mock_open,
        ):
            result = asyncio.run(handler({}))
        mock_open.assert_called_once_with("http://localhost:5555/?viz=force")
        assert "force" in result["url"]
        assert "Workflow graph" in result["message"]

    def test_bootstrap_url_skips_launch_server(self):
        """When the bootstrap reports a live URL the handler must NOT
        call launch_server — the old unconditional call is the
        double-spawn race that leaked instances on ephemeral ports."""
        mock_launch = MagicMock(return_value="http://127.0.0.1:3458")
        with (
            patch(
                "mcp_server.handlers.open_visualization._url_from_bootstrap",
                return_value="http://127.0.0.1:56746",
            ),
            patch(
                "mcp_server.handlers.open_visualization._find_dev_source",
                return_value=None,
            ),
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                mock_launch,
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            result = asyncio.run(handler({}))
        mock_launch.assert_not_called()
        assert result["url"] == "http://127.0.0.1:56746/?viz=force"


class TestUrlFromBootstrap:
    """``_url_from_bootstrap`` parses + verifies the bootstrap status
    line. Verification (HTTP probe) is stubbed via urllib."""

    def _probe_ok(self):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=MagicMock(read=lambda n: b"x"))
        ctx.__exit__ = MagicMock(return_value=False)
        return patch("urllib.request.urlopen", return_value=ctx)

    def test_parses_reuse_line(self):
        line = "ok reused pid=123 synced=4 url=http://127.0.0.1:56746/?viz=force"
        with self._probe_ok():
            assert _url_from_bootstrap(line) == "http://127.0.0.1:56746"

    def test_parses_spawn_line(self):
        line = "ok synced=9 url=http://127.0.0.1:3458/?viz=force extras=ok"
        with self._probe_ok():
            assert _url_from_bootstrap(line) == "http://127.0.0.1:3458"

    def test_rejects_failure_status(self):
        assert _url_from_bootstrap("no_dev_source") is None
        assert _url_from_bootstrap("bootstrap_failed: OSError: x") is None

    def test_rejects_non_loopback_url(self):
        line = "ok synced=1 url=http://evil.example:80/?viz=force extras=ok"
        with self._probe_ok():
            assert _url_from_bootstrap(line) is None

    def test_unreachable_server_returns_none(self):
        line = "ok synced=1 url=http://127.0.0.1:3458/?viz=force extras=ok"
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            assert _url_from_bootstrap(line) is None


class TestDevSourceSecurityHardening:
    """Falsification tests for GHSA-gvpp-v77h-5w8g — `_find_dev_source`
    must not be persuadable by attacker-controllable env vars.

    Each test would fail if a regression re-introduced
    ``CLAUDE_PROJECT_DIR`` as a candidate, or removed the explicit
    ``CORTEX_DEV_SOURCE_SYNC=1`` opt-in for ``CORTEX_DEV_ROOT``. The
    threat model is: an attacker tricks the user into opening a
    malicious project in Claude Code (which sets
    ``CLAUDE_PROJECT_DIR``); the malicious project contains the two
    marker files (``mcp_server/`` directory + ``ui/unified-viz.html``)
    that ``_is_cortex_root`` checks, plus a
    ``mcp_server/server/visualize_bootstrap.py`` containing arbitrary
    Python. When the user runs ``/cortex-visualize`` the handler used
    to ``subprocess.run`` that file, giving the attacker local ACE.
    """

    @staticmethod
    def _plant_marker_files(root: Path) -> None:
        (root / "mcp_server" / "server").mkdir(parents=True, exist_ok=True)
        (root / "ui").mkdir(parents=True, exist_ok=True)
        (root / "ui" / "unified-viz.html").write_text(
            "<html>attacker</html>", encoding="utf-8"
        )
        (root / "mcp_server" / "server" / "visualize_bootstrap.py").write_text(
            "raise RuntimeError('attacker-controlled bootstrap')\n",
            encoding="utf-8",
        )

    def test_claude_project_dir_is_ignored(self, monkeypatch):
        # Falsifies: CLAUDE_PROJECT_DIR can drive _find_dev_source.
        with tempfile.TemporaryDirectory(prefix="cortex-malicious-") as td:
            attacker_root = Path(td)
            self._plant_marker_files(attacker_root)
            # Make sure no other env var or home-fallback satisfies
            # the search — otherwise the test would be vacuous.
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.delenv("CORTEX_DEV_ROOT", raising=False)
            monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(attacker_root))
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=attacker_root.parent,
            ):
                # parent dir contains the malicious dir but lacks
                # ``Documents/Developments/Cortex`` so home-fallback
                # cannot accidentally satisfy.
                result = _find_dev_source()
            assert result is None, (
                f"CLAUDE_PROJECT_DIR should be ignored; got {result!r} — "
                "this would re-introduce GHSA-gvpp-v77h-5w8g."
            )

    def test_cortex_dev_root_ignored_without_opt_in(self, monkeypatch):
        # Falsifies: CORTEX_DEV_ROOT is honoured without the
        # CORTEX_DEV_SOURCE_SYNC=1 flag.
        with tempfile.TemporaryDirectory(prefix="cortex-unopted-") as td:
            attacker_root = Path(td)
            self._plant_marker_files(attacker_root)
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(attacker_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=attacker_root.parent,
            ):
                result = _find_dev_source()
            assert result is None, (
                f"CORTEX_DEV_ROOT honoured without the opt-in flag; got {result!r}."
            )

    def test_cortex_dev_root_honoured_when_explicitly_opted_in(self, monkeypatch):
        # Falsifies: opt-in flag is broken (legitimate dev workflow
        # would also break). This test exists so we don't over-lock
        # the door and lose the intended developer affordance.
        with tempfile.TemporaryDirectory(prefix="cortex-dev-real-") as td:
            dev_root = Path(td)
            self._plant_marker_files(dev_root)
            monkeypatch.setenv("CORTEX_DEV_SOURCE_SYNC", "1")
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(dev_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=dev_root.parent,
            ):
                result = _find_dev_source()
            assert result == dev_root, (
                f"Opt-in path broken: expected {dev_root!r}, got {result!r}."
            )

    def test_opt_in_flag_value_not_1_is_rejected(self, monkeypatch):
        # Falsifies: ANY non-empty CORTEX_DEV_SOURCE_SYNC value
        # activates the gate (would let an accidental "true"/"yes"
        # in a shell rc file pull in CORTEX_DEV_ROOT).
        with tempfile.TemporaryDirectory(prefix="cortex-truthy-") as td:
            root = Path(td)
            self._plant_marker_files(root)
            monkeypatch.setenv("CORTEX_DEV_SOURCE_SYNC", "true")
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=root.parent,
            ):
                result = _find_dev_source()
            assert result is None, (
                "Gate must require the exact string '1' to avoid "
                "ambiguous truthy values silently re-opening the hole."
            )
