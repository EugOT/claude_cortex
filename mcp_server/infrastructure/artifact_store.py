"""Content-addressed filesystem store for full raw tool-output artifacts.

When an auto-captured tool output exceeds GIST_BUDGET, the full raw output is
written here and the memory body keeps only a gist + a pointer to the artifact
path (see core/gist_extraction.py and tasks/bounded-io-phase2-design.md F3).
The artifact is a plain Markdown file loadable by the Read tool — zero new MCP
surface, nothing dropped from the corpus.

Content addressing (sha256 of the content) makes repeated identical outputs
dedup to a single file, and monthly sharding (<yyyy-mm>/) keeps directory
fan-out bounded over time.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.infrastructure.config import METHODOLOGY_DIR

ARTIFACTS_DIR = METHODOLOGY_DIR / "artifacts"

# sha256 hex is 64 chars; the first 16 (64 bits) give a collision-free key for
# the artifact corpus (millions of files → negligible birthday-collision risk)
# while keeping filenames short. Mirrors backfill_helpers.file_hash([:16]).
_ADDRESS_LEN = 16


def store_artifact(content: str, *, created_at: datetime | None = None) -> Path:
    """Write ``content`` to a content-addressed Markdown artifact, return path.

    Pre: content is a string. created_at, if given, dates the monthly shard;
    defaults to now (UTC).
    Post: the file ``ARTIFACTS_DIR/<yyyy-mm>/<sha256(content)[:16]>.md`` exists
    and holds ``content`` as UTF-8. Content-addressed: if the file already
    exists it is NOT rewritten (dedup — identical content maps to one path).
    Parent directories are created as needed. Returns the artifact path.
    """
    when = created_at or datetime.now(timezone.utc)
    shard = ARTIFACTS_DIR / f"{when.year:04d}-{when.month:02d}"
    address = hashlib.sha256(content.encode("utf-8")).hexdigest()[:_ADDRESS_LEN]
    path = shard / f"{address}.md"
    if path.exists():
        return path
    shard.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
