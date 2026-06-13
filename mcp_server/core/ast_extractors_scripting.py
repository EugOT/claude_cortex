"""Tree-sitter extractors for scripting languages: Ruby and PHP.

Node-type names verified empirically against tree-sitter-language-pack
grammars (ruby, php). Ruby imports are ``require``/``require_relative``
call sites; PHP imports are ``namespace_use_clause`` nodes.

Split from ast_extractors.py to stay under 300 lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.ast_extractors import _find_children, _text, _walk_type
from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node


# ── Ruby ──────────────────────────────────────────────────────────────────────

_RUBY_REQUIRE = {"require", "require_relative", "load"}


def extract_ruby_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Ruby require/require_relative/load call sites."""
    imports: list[ImportInfo] = []
    for call in _walk_type(root, "call"):
        method = call.child_by_field_name("method")
        if not method or _text(method, source) not in _RUBY_REQUIRE:
            continue
        args = call.child_by_field_name("arguments")
        if args:
            mod = _text(args, source).strip().strip("()").strip().strip("\"'")
            if mod:
                imports.append(ImportInfo(module=mod))
    return imports


_RUBY_KINDS = {"class": "class", "module": "module"}


def extract_ruby_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Ruby class, module, and method definitions."""
    defs: list[SymbolDef] = []
    _walk_ruby(root, source, defs, "")
    return defs


def _walk_ruby(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Recursively extract Ruby definitions, qualifying methods by class."""
    if node.type in _RUBY_KINDS:
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            defs.append(SymbolDef(name=n, kind=_RUBY_KINDS[node.type]))
            for child in node.children:
                _walk_ruby(child, source, defs, n)
            return
    if node.type == "method":
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            full = f"{parent}.{n}" if parent else n
            defs.append(SymbolDef(name=full, kind="method" if parent else "function"))
        return
    for child in node.children:
        _walk_ruby(child, source, defs, parent)


# ── PHP ───────────────────────────────────────────────────────────────────────


def extract_php_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract PHP `use` namespace import clauses."""
    imports: list[ImportInfo] = []
    for clause in _walk_type(root, "namespace_use_clause"):
        mod = _text(clause, source).strip().rstrip(";").strip()
        if mod:
            imports.append(ImportInfo(module=mod))
    return imports


_PHP_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
    "enum_declaration": "enum",
}


def extract_php_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract PHP class, interface, trait, function, and method definitions."""
    defs: list[SymbolDef] = []
    _walk_php(root, source, defs, "")
    return defs


def _walk_php(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Recursively extract PHP definitions, qualifying methods by type."""
    if node.type in _PHP_KINDS:
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            defs.append(SymbolDef(name=n, kind=_PHP_KINDS[node.type]))
            for child in _find_children(node, "declaration_list"):
                for member in child.children:
                    _walk_php(member, source, defs, n)
            return
    if node.type in ("function_definition", "method_declaration"):
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            full = f"{parent}.{n}" if parent else n
            defs.append(SymbolDef(name=full, kind="method" if parent else "function"))
        return
    for child in node.children:
        _walk_php(child, source, defs, parent)
