#!/usr/bin/env python3
"""Cross-platform launcher for Cortex MCP server and hooks.

Sets up PYTHONPATH, DATABASE_URL, and working directory, then runs the
target module. Works on Windows (cmd.exe), macOS, and Linux — no bash
or shell-specific syntax required.

Usage:
    python3 scripts/launcher.py <module> [--install-deps]

Examples:
    python3 scripts/launcher.py mcp_server                       # MCP server
    python3 scripts/launcher.py mcp_server.hooks.session_start   # Hook
    python3 scripts/launcher.py mcp_server.hooks.auto_recall     # Hook
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _resolve_paths() -> tuple[str, str]:
    """Resolve plugin root and deps directory."""
    # CLAUDE_PLUGIN_ROOT is set by Claude Code for plugins
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not plugin_root or not Path(plugin_root).is_dir():
        # Fall back to this script's parent's parent
        plugin_root = str(Path(__file__).resolve().parent.parent)

    # CLAUDE_PLUGIN_DATA is set by Claude Code — persistent across updates
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if plugin_data:
        deps_dir = os.path.join(plugin_data, "deps")
    else:
        deps_dir = os.path.join(plugin_root, "deps")

    return plugin_root, deps_dir


def _ensure_deps(deps_dir: str) -> None:
    """Install minimal dependencies if missing.

    The plugin's MCP server, hooks, and handlers all transitively import
    the full base runtime (fastmcp, pydantic, pydantic-settings, numpy)
    plus the postgres trio (psycopg, psycopg_pool, pgvector). When the
    plugin runs against system python (the marketplace install path),
    none of these are guaranteed to be present, so any missing one
    causes an ImportError before the MCP server registers tools or a
    hook can read its payload. Install whatever's missing in a single
    pip call so partial states (e.g., pydantic present but fastmcp
    absent after a python upgrade) self-heal.
    """
    os.makedirs(deps_dir, exist_ok=True)
    # Base runtime (every entry point) + postgres trio (pg_store
    # hard-imports at module load): (import_name, pip_spec).
    required = [
        ("fastmcp", "fastmcp>=2.0.0"),
        ("pydantic", "pydantic>=2.0.0"),
        ("pydantic_settings", "pydantic-settings>=2.0.0"),
        ("numpy", "numpy>=1.24.0"),
        ("psycopg", "psycopg[binary]>=3.1"),
        ("psycopg_pool", "psycopg_pool>=3.2"),
        ("pgvector", "pgvector>=0.3"),
    ]
    missing = [spec for name, spec in required if not _importable(name, deps_dir)]
    if not missing:
        return
    _pip_install(deps_dir, missing)


def _importable(import_name: str, deps_dir: str) -> bool:
    """True iff ``import_name`` resolves to a REAL package.

    A bare ``import pkg`` succeeds even for the husk an interrupted
    ``pip install --target`` leaves behind: the package directory
    exists but has no ``__init__.py``, so Python imports it as a
    NAMESPACE package (``__file__ is None``) and every
    ``from pkg import X`` later dies with "unknown location". Because
    deps_dir is first on sys.path, that husk shadows any healthy
    install and the MCP server fails to connect on every retry
    (observed 2026-06-12: deps/fastmcp without __init__.py →
    "cannot import name 'FastMCP' from 'fastmcp' (unknown location)").

    When a husk is detected inside deps_dir it is deleted so the
    reinstall lands clean.
    """
    import importlib

    try:
        mod = importlib.import_module(import_name)
    except ImportError:
        return False
    if getattr(mod, "__file__", None) is not None:
        return True
    # Namespace husk — evict from sys.modules and remove the partial
    # directory if it lives in our deps dir, then report missing.
    sys.modules.pop(import_name, None)
    husk = os.path.join(deps_dir, import_name)
    if os.path.isdir(husk):
        import shutil

        shutil.rmtree(husk, ignore_errors=True)
        print(
            f"[cortex-launcher] removed corrupt partial install: {husk}",
            file=sys.stderr,
        )
    return False


def _pip_install(deps_dir: str, packages: list[str]) -> None:
    """Install ``packages`` into ``deps_dir``, surfacing failures.

    The previous version swallowed pip's output entirely
    (capture_output=True, no returncode check), so on any machine where
    pip fails — corporate proxy, no network, PEP 668
    externally-managed interpreter — the launcher continued, the target
    module died with a bare ImportError, and Claude Code reported only
    "failed to connect" with no cause (observed 2026-06-12).

    PEP 668 interpreters refuse ``pip install`` with an
    ``externally-managed-environment`` error; per PEP 668 the explicit
    user-requested override is ``--break-system-packages``. Installing
    with ``--target`` into the plugin's own deps dir never touches the
    system site-packages, so the override is safe here. We retry with
    the flag only when pip's own error names that condition.

    The install is ATOMIC with respect to deps_dir: pip targets a
    sibling temp dir, and only fully-installed top-level entries are
    moved into deps_dir afterwards. If the launcher is killed
    mid-install (e.g. the MCP client's startup timeout on a slow first
    bootstrap), deps_dir is untouched — the kill leaves an orphan temp
    dir, not the namespace husk that used to shadow every later launch
    (observed 2026-06-12).
    """
    import shutil

    tmp_dir = f"{deps_dir}.tmp-{os.getpid()}"
    base = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "--target",
        tmp_dir,
        *packages,
    ]
    try:
        proc = subprocess.run(base, capture_output=True, text=True)
        err = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode != 0 and "externally-managed-environment" in err:
            proc = subprocess.run(
                base + ["--break-system-packages"],
                capture_output=True,
                text=True,
            )
            err = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode != 0:
            print(
                "[cortex-launcher] dependency install failed for "
                f"{', '.join(packages)} (python {sys.executable}).\n"
                f"[cortex-launcher] pip said:\n{err.strip()[-2000:]}\n"
                "[cortex-launcher] Fix the pip failure above (network/"
                "proxy/permissions), or pre-install the packages, then "
                "reconnect the cortex MCP server.",
                file=sys.stderr,
            )
            return
        # Commit: move each fully-installed entry into deps_dir.
        for entry in os.listdir(tmp_dir):
            dest = os.path.join(deps_dir, entry)
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            elif os.path.exists(dest):
                os.remove(dest)
            os.replace(os.path.join(tmp_dir, entry), dest)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _ensure_all_deps(deps_dir: str) -> None:
    """Install all dependencies including ML packages."""
    _ensure_deps(deps_dir)
    if not _importable("sentence_transformers", deps_dir):
        _pip_install(
            deps_dir,
            ["sentence-transformers>=2.2.0", "flashrank>=0.2.0"],
        )


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 scripts/launcher.py <module> [--install-deps]",
            file=sys.stderr,
        )
        sys.exit(1)

    module = sys.argv[1]
    install_deps = "--install-deps" in sys.argv

    plugin_root, deps_dir = _resolve_paths()

    # Set up environment
    path_sep = ";" if sys.platform == "win32" else ":"
    current_pypath = os.environ.get("PYTHONPATH", "")
    new_paths = [plugin_root, deps_dir]
    if current_pypath:
        new_paths.append(current_pypath)
    os.environ["PYTHONPATH"] = path_sep.join(new_paths)

    # Ensure PYTHONPATH entries are in sys.path for this process
    for p in [plugin_root, deps_dir]:
        if p not in sys.path:
            sys.path.insert(0, p)

    # Set DATABASE_URL default if not set
    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = "postgresql://localhost:5432/cortex"

    # Install deps. The base-deps check is a tight no-op when everything
    # is already present, so we always run it — every entry point (server,
    # hooks, doctor) imports the same base stack and crashes the same way
    # if anything is missing. SessionStart additionally needs the heavy
    # ML stack (sentence-transformers, flashrank).
    if module == "mcp_server.hooks.session_start" or install_deps:
        _ensure_all_deps(deps_dir)
    else:
        _ensure_deps(deps_dir)

    # Change to plugin root
    os.chdir(plugin_root)

    # Run the target module
    sys.argv = [module] + [a for a in sys.argv[2:] if a != "--install-deps"]
    try:
        from runpy import run_module

        run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[cortex-launcher] Failed to run {module}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
