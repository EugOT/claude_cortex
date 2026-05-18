"""Constants for the seed_project discovery stages.

Heat values, config file names, doc globs, entry points, CI/CD files,
ignored directories, and language extension mappings.
"""

from __future__ import annotations

HEAT_BY_TYPE = {
    "structural_summary": 0.9,
    "documentation": 0.85,
    "entry_point": 0.80,
    "config": 0.70,
    "ci_cd": 0.60,
}

CONFIG_FILES = [
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "composer.json",
    ".ruby-version",
    "Gemfile",
    "mix.exs",
]

DOC_GLOBS = ["README*", "CLAUDE*", "CONTRIBUTING*", "CHANGELOG*", "ARCHITECTURE*"]
DOC_DIRS = ["docs", "doc", "documentation", "adr", "docs/adr"]

ENTRY_POINT_NAMES = {
    "__main__.py",
    "main.py",
    "app.py",
    "server.py",
    "cli.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "server.js",
    "main.go",
    "cmd/main.go",
    "main.rs",
    "src/main.rs",
    "Main.java",
}

CI_FILES = [
    ".github/workflows",
    "Makefile",
    "makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "tox.ini",
    ".travis.yml",
    "circle.yml",
    ".circleci",
    "Jenkinsfile",
    ".gitlab-ci.yml",
    "bitbucket-pipelines.yml",
]

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    "coverage",
    ".coverage",
    "htmlcov",
    "site-packages",
    ".tox",
    ".nox",
    # 2026-05-17 (user feedback): seed_project was producing wiki pages
    # titled ``Spec: Entry point: .claude/worktrees/agent-a0ceb782/...``
    # because per-agent git worktrees were treated as real source trees.
    # A worktree is a transient build of the same code — seeding it
    # creates N duplicate sets of stub pages. Same for ``.claude/``
    # itself (settings, hooks, agent state) and for ``deps/`` vendored
    # third-party trees we don't author.
    ".claude",
    "worktrees",
    "deps",
    "vendor",
    "third_party",
    "external",
    # pytest temp directories (``/private/var/folders/.../pytest-of-*``)
    # leak into seeded titles when test runs invoke seed_project on
    # fixture repos like ``repo-a``/``repo-b``. They're caught by the
    # path-based skip in seed_project_stages.is_test_fixture_path().
}

# 2026-05-17: path-fragment predicate complementing IGNORE_DIRS. Returns
# True if the absolute path looks like a pytest temp fixture root or a
# transient agent worktree — both should be silently rejected by
# seed_project before any pages are generated.
TEST_FIXTURE_PATH_MARKERS = (
    "pytest-of-",
    "/private/var/folders/",
    "/var/folders/",
    ".claude/worktrees/",
)


def is_transient_seed_root(path: str) -> bool:
    """Return True when ``path`` is a known transient/test/worktree root
    that ``seed_project`` should refuse to operate on. Used at the
    handler entry point so test runs and worktree creation never pollute
    the wiki with stub pages."""
    p = str(path)
    return any(marker in p for marker in TEST_FIXTURE_PATH_MARKERS)


EXT_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".scala": "Scala",
    ".clj": "Clojure",
    ".hs": "Haskell",
}
