"""Tests for the extra-language tree-sitter extractors.

Covers Java, Kotlin, C, C++, C#, Ruby, PHP via the public parse_file_ast
entry point. Skipped when tree-sitter is not installed.
"""

from __future__ import annotations

import pytest

from mcp_server.core.ast_parser import AST_SUPPORTED, is_available, parse_file_ast

pytestmark = pytest.mark.skipif(not is_available(), reason="tree-sitter not installed")


def _defs(path: str, src: bytes) -> dict[str, str]:
    fa = parse_file_ast(path, src)
    return {d.name: d.kind for d in fa.definitions}


def _imports(path: str, src: bytes) -> list[str]:
    return [i.module for i in parse_file_ast(path, src).imports]


def test_all_langs_registered() -> None:
    for lang in ("java", "kotlin", "c", "cpp", "csharp", "ruby", "php"):
        assert lang in AST_SUPPORTED


def test_java() -> None:
    src = b"import java.util.List;\nclass Foo extends Bar { void m() {} }\nenum E { A }"
    defs = _defs("Foo.java", src)
    assert defs["Foo"] == "class"
    assert defs["Foo.m"] == "method"
    assert defs["E"] == "enum"
    assert "java.util.List" in _imports("Foo.java", src)


def test_kotlin() -> None:
    src = b"import kotlin.io.println\nclass Foo { fun m() {} }\nfun top() {}"
    defs = _defs("Foo.kt", src)
    assert defs["Foo"] == "class"
    assert defs["Foo.m"] == "method"
    assert defs["top"] == "function"
    assert "kotlin.io.println" in _imports("Foo.kt", src)


def test_c() -> None:
    src = b"#include <stdio.h>\nint add(int a){ return a; }\nstruct Pt { int x; };"
    defs = _defs("foo.c", src)
    assert defs["add"] == "function"
    assert defs["Pt"] == "class"
    assert "stdio.h" in _imports("foo.c", src)


def test_cpp() -> None:
    src = b"namespace n { class Foo { void m(); }; }\nvoid Foo::m(){}"
    defs = _defs("foo.cpp", src)
    assert defs["Foo"] == "class"
    assert defs["n"] == "namespace"
    assert defs["Foo::m"] == "method"


def test_csharp() -> None:
    src = b"using System;\nnamespace N { class Foo { void M(){} } interface I {} }"
    defs = _defs("Foo.cs", src)
    assert defs["Foo"] == "class"
    assert defs["Foo.M"] == "method"
    assert defs["I"] == "interface"
    assert "System" in _imports("Foo.cs", src)


def test_ruby() -> None:
    src = b'require "set"\nclass Foo\n def m\n end\nend\nmodule M\nend'
    defs = _defs("foo.rb", src)
    assert defs["Foo"] == "class"
    assert defs["Foo.m"] == "method"
    assert defs["M"] == "module"
    assert "set" in _imports("foo.rb", src)


def test_php() -> None:
    src = b"<?php\nuse App\\Bar;\nclass Foo { function m() {} }\nfunction top() {}"
    defs = _defs("foo.php", src)
    assert defs["Foo"] == "class"
    assert defs["Foo.m"] == "method"
    assert defs["top"] == "function"
    assert "App\\Bar" in _imports("foo.php", src)
