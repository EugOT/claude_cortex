"""Wiki endpoint dispatchers for the standalone server.

Each function here owns one HTTP verb on ``/api/wiki/*`` and delegates
the actual work to ``mcp_server.handlers.wiki_api``. Extracted from
``http_standalone.py`` so the main file stays under 300 lines.

Every function uses ``http_standalone_response.send_json_ok`` /
``send_json_error`` to keep the HTTP response boilerplate in one place.
"""

from __future__ import annotations

import json
import urllib.parse

from mcp_server.server.http_standalone_response import (
    send_json_error,
    send_json_ok,
)

# Compile-time allowlist for the export download filename (CodeQL
# py/http-response-splitting). The output can only be one of four
# constant strings — user input cannot reach the Content-Disposition
# header.
_EXPORT_FILENAMES = {
    "pdf": "cortex-export.pdf",
    "tex": "cortex-export.tex",
    "docx": "cortex-export.docx",
    "html": "cortex-export.html",
}


def qs_map(path: str) -> dict[str, str]:
    """Parse ``?k=v&k2=v2`` into a plain dict. URL-unquotes values."""
    out: dict[str, str] = {}
    if "?" not in path:
        return out
    for kv in path.split("?", 1)[1].split("&"):
        if not kv:
            continue
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[k] = urllib.parse.unquote(v)
        else:
            out[kv] = ""
    return out


def serve_wiki_list(handler) -> None:
    """GET /api/wiki/list → {pages: [...]}."""
    try:
        from mcp_server.handlers.wiki_api import list_wiki_pages
        from mcp_server.infrastructure.config import METHODOLOGY_DIR

        data = list_wiki_pages(METHODOLOGY_DIR / "wiki")
        send_json_ok(handler, {"pages": data})
    except Exception as e:
        send_json_error(handler, e)


def serve_wiki_page(handler) -> None:
    """GET /api/wiki/page?path=<rel> → page body."""
    try:
        from mcp_server.handlers.wiki_api import read_wiki_page
        from mcp_server.infrastructure.config import METHODOLOGY_DIR

        rel_path = qs_map(handler.path).get("path", "")
        send_json_ok(handler, read_wiki_page(METHODOLOGY_DIR / "wiki", rel_path))
    except Exception as e:
        send_json_error(handler, e)


def serve_wiki_projects(handler) -> None:
    """GET /api/wiki/projects → project-organized index of the wiki.

    Returns one entry per project (domain) with:
      * Page counts split by kind (architecture, services, api, adr…).
      * Scope coverage ratio (how many of the six structural scopes are
        documented).
      * File coverage ratio (how many source files appear in any page).
      * Sample missing scopes for the UI to surface as "needs work".

    This is the landing-page endpoint: a non-technical user opens the
    wiki, sees every project they have at a glance with what's covered
    and what's missing — and clicks into each to drill down.
    """
    try:
        from mcp_server.core.wiki_coverage import (
            audit_all_domains,
            audit_all_file_coverage,
        )
        from mcp_server.handlers.wiki_api import list_wiki_pages
        from mcp_server.infrastructure.config import METHODOLOGY_DIR

        wiki_root = METHODOLOGY_DIR / "wiki"
        pages = list_wiki_pages(wiki_root)

        # Group pages by domain (path segment 1) and kind (segment 0).
        # Pages stored at ``<kind>/<domain>/<slug>.md`` produce both
        # fields; anything else lands under ``_general``.
        by_domain: dict[str, dict[str, list[dict]]] = {}
        for p in pages:
            path = p.get("rel_path") or p.get("path") or ""
            parts = path.split("/")
            if len(parts) >= 3:
                kind, domain = parts[0], parts[1]
            elif len(parts) == 2:
                kind, domain = parts[0], "_general"
            else:
                continue
            if domain.startswith("_") and domain != "_general":
                continue
            by_domain.setdefault(domain, {}).setdefault(kind, []).append(
                {
                    "path": path,
                    "title": p.get("title") or "",
                }
            )

        # Layer scope and file coverage onto each domain.
        scope_audits = {c.domain: c for c in audit_all_domains(str(wiki_root))}
        file_audits = {r.domain: r for r in audit_all_file_coverage(str(wiki_root))}

        projects: list[dict] = []
        for domain, kinds in sorted(by_domain.items()):
            cov = scope_audits.get(domain)
            fc = file_audits.get(domain)
            counts = {kind: len(items) for kind, items in kinds.items()}
            project = {
                "domain": domain,
                "page_total": sum(counts.values()),
                "page_counts_by_kind": counts,
                "scope_covered": cov.covered_count if cov else 0,
                "scope_total": len(cov.scopes) if cov else 0,
                "scope_coverage_ratio": (round(cov.coverage_ratio, 3) if cov else None),
                "missing_scopes": (
                    [s.scope.name for s in cov.missing_scopes()] if cov else []
                ),
                "file_covered": fc.covered_file_count if fc else None,
                "file_total": fc.source_file_count if fc else None,
                "file_coverage_ratio": (round(fc.coverage_ratio, 3) if fc else None),
            }
            projects.append(project)

        send_json_ok(handler, {"projects": projects})
    except Exception as e:
        send_json_error(handler, e)


def _dispatch_wiki_db(op: str, qs: dict[str, str]) -> dict:
    """Resolve a DB-backed op name to a wiki_api call result."""
    from mcp_server.handlers import wiki_api
    from mcp_server.infrastructure.config import METHODOLOGY_DIR

    if op == "page_meta":
        return wiki_api.page_meta(qs.get("path", ""))
    if op == "concepts":
        return wiki_api.list_concepts(
            qs.get("status") or None, int(qs.get("limit", "100"))
        )
    if op == "drafts":
        return wiki_api.list_drafts(
            qs.get("status") or None,
            qs.get("kind") or None,
            int(qs.get("limit", "100")),
        )
    if op == "memos":
        if not qs.get("subject_id"):
            return {"error": "subject_id required"}
        return wiki_api.list_memos(
            qs.get("subject_type", "page"),
            int(qs["subject_id"]),
            int(qs.get("limit", "50")),
        )
    if op == "views":
        return wiki_api.list_views()
    if op == "view":
        return wiki_api.execute_view(qs.get("name") or None, qs.get("query") or None)
    if op == "bibliography":
        return wiki_api.list_bibliography(METHODOLOGY_DIR / "wiki")
    if op == "bibliography_read":
        return wiki_api.read_bibliography(METHODOLOGY_DIR / "wiki", qs.get("path", ""))
    return {"error": f"unknown op: {op}"}


def _truthy(v: str) -> bool:
    """Parse a query-string flag. Pre: v is the raw value. Post: True for
    1/true/yes/on (case-insensitive); False otherwise (incl. empty)."""
    return v.strip().lower() in ("1", "true", "yes", "on")


def serve_wiki_graph(handler) -> None:
    """GET /api/wiki/graph?domain=&cooccur=&xlens= → workflow_graph.v1.

    Read-only cross-lens documentation graph for one domain. Mirrors
    serve_wiki_db: parse query, call wiki_api.wiki_graph, send_json_ok.
    """
    try:
        from mcp_server.handlers.wiki_api import wiki_graph

        qs = qs_map(handler.path)
        data = wiki_graph(
            qs.get("domain", ""),
            cooccur=_truthy(qs.get("cooccur", "")),
            xlens=_truthy(qs.get("xlens", "")),
        )
        send_json_ok(handler, data)
    except Exception as e:
        send_json_error(handler, e)


def serve_wiki_db(handler, op: str) -> None:
    """Route every read-only DB-backed wiki endpoint."""
    try:
        data = _dispatch_wiki_db(op, qs_map(handler.path))
        send_json_ok(handler, data)
    except Exception as e:
        send_json_error(handler, e)


def _send_export_download(handler, result: dict, data: bytes) -> None:
    """Emit the Content-Disposition download headers + body."""
    from mcp_server.server.http_common import _apply_cors_headers

    safe_filename = _EXPORT_FILENAMES.get(result.get("format", ""), "cortex-export.bin")
    handler.send_response(200)
    handler.send_header("Content-Type", result["mime"])
    handler.send_header(
        "Content-Disposition",
        f'attachment; filename="{safe_filename}"',
    )
    handler.send_header("Content-Length", str(len(data)))
    _apply_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(data)


def serve_wiki_export(handler) -> None:
    """GET /api/wiki/export?path=...&format=pdf|tex|docx|html → download."""
    try:
        import asyncio
        import base64

        from mcp_server.handlers.wiki_export import handler as _export

        qs = qs_map(handler.path)
        rel_path = qs.get("path", "")
        fmt = qs.get("format", "pdf")
        result = asyncio.run(_export({"rel_path": rel_path, "format": fmt}))
        if not result.get("ok"):
            send_json_ok(handler, result)
            return
        data = base64.b64decode(result["content_base64"])
        _send_export_download(handler, result, data)
    except Exception as e:
        send_json_error(handler, e)


def serve_wiki_save(handler) -> None:
    """POST /api/wiki/save — body: JSON {rel_path, body}."""
    try:
        from mcp_server.handlers.wiki_api import save_wiki_page
        from mcp_server.infrastructure.config import METHODOLOGY_DIR

        length = int(handler.headers.get("Content-Length") or 0)
        if length <= 0 or length > 4_000_000:
            handler.send_response(400)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(
                json.dumps({"error": "invalid content-length"}).encode()
            )
            return
        payload = json.loads(handler.rfile.read(length))
        rel_path = payload.get("rel_path", "")
        body = payload.get("body", "")
        result = save_wiki_page(METHODOLOGY_DIR / "wiki", rel_path, body)
        send_json_ok(handler, result)
    except Exception as e:
        send_json_error(handler, e)
