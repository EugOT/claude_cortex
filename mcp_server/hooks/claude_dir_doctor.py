"""SessionStart hygiene doctor for the ~/.claude plugin directory.

REPORT-FIRST diagnostic hook. Mechanically checkable invariants that
were violated by real incidents on 2026-06-10 are now verified every
session instead of living only in instructions (DB-wipe postmortem
principle: checkable facts belong in code that runs every session).

Each check is individually try/except-wrapped — the hook must NEVER
break session start: stderr ``[cortex-doctor]`` lines, silent when
healthy, always exit 0. The ONLY mutation is deleting a provably-useless
(0-node) viz snapshot; everything else is report-only because the safe
repair is not knowable from local facts (e.g. the right symlink target).

Path constants are module-level so tests can monkeypatch them.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from mcp_server.hooks.claude_dir_artifacts import (
    check_symlink_sanity,
    check_viz_snapshot,
)

_PREFIX = "[cortex-doctor]"

# Module-level paths — monkeypatched by tests against a tmp_path tree.
# (Binary/snapshot paths live in claude_dir_artifacts; this module owns
# the plugin-registry paths.)
CLAUDE_DIR = Path.home() / ".claude"
PLUGINS_DIR = CLAUDE_DIR / "plugins"
INSTALLED_PLUGINS_PATH = PLUGINS_DIR / "installed_plugins.json"
MARKETPLACES_DIR = PLUGINS_DIR / "marketplaces"
PLUGIN_CACHE_DIR = PLUGINS_DIR / "cache"

_SELF_TIMEOUT_SECONDS = 5  # hard ceiling; <1s is the target
_AUTOUPDATE_TIMEOUT_SECONDS = 60  # only when CORTEX_DOCTOR_AUTOUPDATE=1


def _emit(line: str) -> None:
    """Write one finding to stderr with the doctor prefix."""
    print(f"{_PREFIX} {line}", file=sys.stderr)


def _parse_semver(value: str) -> tuple[int, ...] | None:
    """Parse ``"1.2.3"`` → ``(1, 2, 3)``; ``None`` when unparseable.

    Never raises: an unparseable version is "unknown" to callers, not a
    crash (incident 2026-06-10b: a cache on an old version surfaced
    nothing because no comparison ever ran).
    """
    parts = value.strip().lstrip("v").split(".")
    out: list[int] = []
    for part in parts:
        digits = "".join(c for c in part if c.isdigit())
        if not digits:
            return None
        out.append(int(digits))
    return tuple(out) if out else None


def _load_json(path: Path) -> object | None:
    """Read+parse JSON; ``None`` on any error (malformed file tolerated)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _marketplace_versions(name: str) -> dict[str, tuple[int, ...] | None]:
    """Map plugin-name → parsed version from one marketplace manifest.

    Reads the LOCAL clone only (no network). Returns ``{}`` when the
    manifest is missing or malformed.
    """
    manifest = _load_json(
        MARKETPLACES_DIR / name / ".claude-plugin" / "marketplace.json"
    )
    if not isinstance(manifest, dict):
        return {}
    out: dict[str, tuple[int, ...] | None] = {}
    for plugin in manifest.get("plugins") or []:
        if isinstance(plugin, dict) and "name" in plugin:
            out[str(plugin["name"])] = _parse_semver(str(plugin.get("version", "")))
    return out


def _run_autoupdate(plugin: str, marketplace: str) -> None:
    """Opt-in (CORTEX_DOCTOR_AUTOUPDATE=1) ``claude plugin update`` call.

    Default is report-only — a mid-session update needs a restart anyway
    (incident 2026-06-10b). 60s timeout; failures reported, never raised.
    """
    target = f"{plugin}@{marketplace}"
    try:
        subprocess.run(
            ["claude", "plugin", "update", target],
            capture_output=True,
            timeout=_AUTOUPDATE_TIMEOUT_SECONDS,
        )
        _emit(f"auto-updated {target} (CORTEX_DOCTOR_AUTOUPDATE=1)")
    except (OSError, subprocess.SubprocessError) as exc:
        _emit(f"auto-update {target} failed: {exc}")


def check_plugin_freshness() -> None:
    """Report installed plugins behind their local marketplace manifest.

    Incident 2026-06-10b: the cortex cache ran 3.18.4 while the repo had
    5 versions of fixes and nothing ever surfaced "your plugin is behind
    its marketplace". Compares installed version vs marketplace version
    by semver tuple; unparseable on either side is skipped ("unknown",
    never a crash).
    """
    data = _load_json(INSTALLED_PLUGINS_PATH)
    if not isinstance(data, dict):
        return
    autoupdate = os.environ.get("CORTEX_DOCTOR_AUTOUPDATE") == "1"
    for key, installs in (data.get("plugins") or {}).items():
        if "@" not in str(key) or not isinstance(installs, list) or not installs:
            continue
        plugin, marketplace = str(key).split("@", 1)
        installed = _parse_semver(str((installs[0] or {}).get("version", "")))
        market = _marketplace_versions(marketplace).get(plugin)
        if installed is None or market is None or installed >= market:
            continue
        iv = ".".join(map(str, installed))
        mv = ".".join(map(str, market))
        _emit(
            f"plugin {plugin} {iv} < marketplace {mv} "
            f"— run: claude plugin update {plugin}@{marketplace}"
        )
        if autoupdate:
            _run_autoupdate(plugin, marketplace)


def _dir_size(path: Path) -> int:
    """Total byte size of a directory tree; partial total tolerated."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return total


def check_stale_cache_versions() -> None:
    """Report cached plugin versions that are NOT the installed one.

    Incident 2026-06-10b: 5 stale cached versions accumulated. Report
    count + size + the ``claude plugin prune`` hint; prune is the
    official tool, so we never delete here.
    """
    data = _load_json(INSTALLED_PLUGINS_PATH)
    if not isinstance(data, dict) or not PLUGIN_CACHE_DIR.is_dir():
        return
    installed: dict[tuple[str, str], str] = {}
    for key, installs in (data.get("plugins") or {}).items():
        if "@" in str(key) and isinstance(installs, list) and installs:
            plugin, market = str(key).split("@", 1)
            installed[(market, plugin)] = str((installs[0] or {}).get("version", ""))
    stale = 0
    size = 0
    for market_dir in PLUGIN_CACHE_DIR.iterdir():
        if not market_dir.is_dir():
            continue
        for plugin_dir in market_dir.iterdir():
            keep = installed.get((market_dir.name, plugin_dir.name))
            if keep is None or not plugin_dir.is_dir():
                continue
            for ver_dir in plugin_dir.iterdir():
                if ver_dir.is_dir() and ver_dir.name != keep:
                    stale += 1
                    size += _dir_size(ver_dir)
    if stale:
        _emit(
            f"{stale} stale cached plugin version(s), {size // 1024} KiB "
            "— run: claude plugin prune"
        )


_CHECKS = (
    check_plugin_freshness,
    check_symlink_sanity,
    check_stale_cache_versions,
    check_viz_snapshot,
)


def run_all_checks() -> None:
    """Run every check, each isolated so one failure cannot abort others."""
    for check in _CHECKS:
        try:
            check()
        except Exception as exc:  # defensive: a check must never break start
            _emit(f"{check.__name__} skipped (non-fatal): {exc}")


def _install_self_timeout() -> None:
    """Arm a SIGALRM hard ceiling so the hook can never stall start.

    Best-effort: platforms without SIGALRM (Windows) skip it.
    """
    try:
        signal.signal(signal.SIGALRM, lambda *_a: sys.exit(0))
        signal.alarm(_SELF_TIMEOUT_SECONDS)
    except (AttributeError, ValueError):
        pass


def main() -> None:
    """Entry point — drain any stdin event, run checks, always exit 0."""
    _install_self_timeout()
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except (OSError, ValueError):
        pass
    run_all_checks()
    sys.exit(0)


if __name__ == "__main__":
    main()
