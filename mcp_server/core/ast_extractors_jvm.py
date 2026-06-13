"""Tree-sitter extractors for JVM languages: Java and Kotlin.

Node-type names verified empirically against tree-sitter-language-pack
grammars (java, kotlin). Split from ast_extractors.py to stay under 300
lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.ast_extractors import _find_children, _text, _walk_type
from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node


# ── Java ────────────────────────────────────────────────────────────────────


def extract_java_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Java import declarations."""
    imports: list[ImportInfo] = []
    for node in _find_children(root, "import_declaration"):
        mod = _text(node, source).replace("import", "", 1).replace("static", "", 1)
        imports.append(ImportInfo(module=mod.strip().rstrip(";").strip()))
    return imports


_JAVA_TYPE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "class",
}


def extract_java_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Java class, interface, enum, record, and method definitions."""
    defs: list[SymbolDef] = []
    _walk_java(root, source, defs, "")
    return defs


def _walk_java(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Recursively extract Java definitions, qualifying methods by class."""
    if node.type in _JAVA_TYPE_KINDS:
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            defs.append(SymbolDef(name=n, kind=_JAVA_TYPE_KINDS[node.type]))
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    _walk_java(child, source, defs, n)
            return
    if node.type in ("method_declaration", "constructor_declaration"):
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            full = f"{parent}.{n}" if parent else n
            defs.append(SymbolDef(name=full, kind="method" if parent else "function"))
        return
    for child in node.children:
        _walk_java(child, source, defs, parent)


# ── Kotlin ──────────────────────────────────────────────────────────────────


def extract_kotlin_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Kotlin import headers."""
    imports: list[ImportInfo] = []
    for header in _walk_type(root, "import_header"):
        ident = _find_children(header, "identifier")
        if ident:
            imports.append(ImportInfo(module=_text(ident[0], source).strip()))
    return imports


def extract_kotlin_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Kotlin class, object, interface, and function definitions."""
    defs: list[SymbolDef] = []
    _walk_kotlin(root, source, defs, "")
    return defs


def _walk_kotlin(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Recursively extract Kotlin definitions, qualifying members by type."""
    if node.type in ("class_declaration", "object_declaration"):
        ident = _find_children(node, "type_identifier")
        if ident:
            n = _text(ident[0], source)
            is_iface = any(c.type == "interface" for c in node.children)
            defs.append(SymbolDef(name=n, kind="interface" if is_iface else "class"))
            for child in node.children:
                if child.type == "class_body":
                    for member in child.children:
                        _walk_kotlin(member, source, defs, n)
            return
    if node.type == "function_declaration":
        ident = _find_children(node, "simple_identifier")
        if ident:
            n = _text(ident[0], source)
            full = f"{parent}.{n}" if parent else n
            defs.append(SymbolDef(name=full, kind="method" if parent else "function"))
        return
    for child in node.children:
        _walk_kotlin(child, source, defs, parent)
