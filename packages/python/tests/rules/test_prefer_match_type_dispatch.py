from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "python/app/parser.py") -> list[Diagnostic]:
    return PreferMatchTypeDispatch().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferMatchTypeDispatch.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_three_branch_isinstance_ladder_as_warning() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ080"
    assert diagnostics[0].severity.value == "warning"
    assert "3-branch isinstance ladder" in diagnostics[0].message


def test_allows_two_branch_ladder() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    return None
"""

    assert _check(source) == []


def test_flags_three_terminating_sibling_checks() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, bytes):
        return binary(value)
    if isinstance(value, dict):
        return mapping(value)
    raise TypeError(type(value))
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "terminating isinstance sequence" in diagnostics[0].message


@pytest.mark.parametrize("unrelated_position", ["before", "after"])
def test_finds_sibling_dispatch_next_to_unrelated_terminating_if(unrelated_position: str) -> None:
    unrelated = "    if ready:\n        return cached()\n"
    dispatch = """    if isinstance(value, str):
        return text(value)
    if isinstance(value, bytes):
        return binary(value)
    if isinstance(value, dict):
        return mapping(value)
"""
    body = unrelated + dispatch if unrelated_position == "before" else dispatch + unrelated
    source = f"def parse(value: object):\n{body}    return None\n"

    assert len(_check(source)) == 1


def test_allows_nonterminating_sibling_checks() -> None:
    source = """
def observe(value: object) -> None:
    if isinstance(value, str):
        strings.add(value)
    if isinstance(value, bytes):
        binaries.add(value)
    if isinstance(value, dict):
        mappings.add(value)
"""

    assert _check(source) == []


def test_allows_mixed_subjects() -> None:
    source = """
def parse(first: object, second: object):
    if isinstance(first, str):
        return text(first)
    elif isinstance(second, bytes):
        return binary(second)
    elif isinstance(first, dict):
        return mapping(first)
    return None
"""

    assert _check(source) == []


def test_allows_guarded_branches() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str) and value:
        return text(value)
    elif isinstance(value, bytes) and value:
        return binary(value)
    elif isinstance(value, dict) and value:
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_repeated_or_overlapping_types() -> None:
    source = """
def parse(value: object):
    if isinstance(value, (str, bytes)):
        return scalar(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_flags_disjoint_tuple_and_union_type_arms() -> None:
    source = """
def parse(value: object):
    if isinstance(value, (str, bytes)):
        return scalar(value)
    elif isinstance(value, dict | list):
        return collection(value)
    elif isinstance(value, int):
        return number(value)
    return None
"""

    assert len(_check(source)) == 1


def test_flags_unshadowed_module_local_classes() -> None:
    source = """
class Text: ...
class Binary: ...
class Mapping: ...

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert len(_check(source)) == 1


def test_allows_imported_class_like_runtime_bindings() -> None:
    source = """
from contracts import Text, Binary, Mapping

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_function_shadow_of_module_class() -> None:
    source = """
class Text: ...
class Binary: ...
class Mapping: ...

def parse(value: object, Text):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_import_rebinding_of_module_classes() -> None:
    source = """
class Text: ...
class Binary: ...
class Mapping: ...
from groups import Text, Binary, Mapping

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "shadow",
    [
        "def Text(): ...",
        "def outer():\n    class Text: ...",
    ],
)
def test_allows_declaration_rebinding_of_module_class(shadow: str) -> None:
    source = f"""
class Text: ...
class Binary: ...
class Mapping: ...
{shadow}

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "declaration",
    [
        "Supported = (str, bytes)",
        "Supported = str | bytes",
        "Supported = load_types()",
    ],
)
def test_allows_runtime_type_group_bindings(declaration: str) -> None:
    source = f"""
{declaration}

def parse(value: object):
    if isinstance(value, Supported):
        return scalar(value)
    elif isinstance(value, dict):
        return mapping(value)
    elif isinstance(value, list):
        return sequence(value)
    return None
"""

    assert _check(source) == []


def test_flags_proven_stdlib_ast_classes() -> None:
    source = """
import ast

def name(node: ast.AST):
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None
"""

    assert len(_check(source)) == 1


def test_flags_directly_imported_stdlib_ast_classes() -> None:
    source = """
from ast import Name, expr, operator

def name(node):
    if isinstance(node, Name):
        return node.id
    elif isinstance(node, expr):
        return "expression"
    elif isinstance(node, operator):
        return "operator"
    return None
"""

    assert len(_check(source)) == 1


def test_allows_shadowed_ast_module() -> None:
    source = """
import ast

def name(ast, node):
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None
"""

    assert _check(source) == []


def test_allows_non_type_stdlib_ast_attributes() -> None:
    source = """
import ast

def name(node):
    if isinstance(node, ast.walk):
        return "walk"
    elif isinstance(node, ast.dump):
        return "dump"
    elif isinstance(node, ast.parse):
        return "parse"
    return None
"""

    assert _check(source) == []


def test_allows_shadowed_isinstance() -> None:
    source = """
def parse(value: object, isinstance):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "nested_import",
    [
        "from fake import check as isinstance",
        "from fake import Text as str",
        "import fake as ast",
    ],
)
def test_allows_function_local_import_shadow(nested_import: str) -> None:
    source = f"""
import ast

def parse(value: object):
    {nested_import}
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, ast.Name):
        return name(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_wildcard_import_with_unproven_bindings() -> None:
    source = """
from fake import *

def parse(value):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        """
def parse(value):
    try:
        load()
    except Exception as isinstance:
        if isinstance(value, str):
            return text(value)
        elif isinstance(value, bytes):
            return binary(value)
        elif isinstance(value, dict):
            return mapping(value)
""",
        """
def parse(value):
    try:
        load()
    except Exception as str:
        if isinstance(value, str):
            return text(value)
        elif isinstance(value, bytes):
            return binary(value)
        elif isinstance(value, dict):
            return mapping(value)
""",
        """
def parse(payload, value):
    match payload:
        case {"fn": isinstance}:
            if isinstance(value, str):
                return text(value)
            elif isinstance(value, bytes):
                return binary(value)
            elif isinstance(value, dict):
                return mapping(value)
""",
        """
def parse(payload, value):
    match payload:
        case {"type": str}:
            if isinstance(value, str):
                return text(value)
            elif isinstance(value, bytes):
                return binary(value)
            elif isinstance(value, dict):
                return mapping(value)
""",
    ],
)
def test_allows_exception_and_pattern_shadow_bindings(source: str) -> None:
    assert _check(source) == []


def test_allows_issubclass_dispatch() -> None:
    source = """
def classify(cls: type):
    if issubclass(cls, Text):
        return "text"
    elif issubclass(cls, Binary):
        return "binary"
    elif issubclass(cls, Mapping):
        return "mapping"
    return None
"""

    assert _check(source) == []


def test_allows_locally_caught_validation_raise() -> None:
    source = """
def parse(value: object):
    try:
        if value is None:
            raise ValueError("required")
        return value
    except ValueError:
        return None
"""

    assert _check(source) == []


def test_allows_sequential_passthrough_guards() -> None:
    source = """
def parse(value: object):
    if value is None:
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value
    return coerce(value)
"""

    assert _check(source) == []


def test_allows_repeated_captures_in_existing_match() -> None:
    source = """
def body(node):
    match node:
        case Function(body=body) | Class(body=body):
            mutate(node)
            return body
    return []
"""

    assert _check(source) == []


def test_allows_generated_source() -> None:
    source = """# Generated by OpenAPI generator. Do not edit.
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_reports_multiple_dispatches_in_source_order() -> None:
    source = """
def first(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)

def second(value: object):
    if isinstance(value, int):
        return integer(value)
    elif isinstance(value, float):
        return floating(value)
    elif isinstance(value, complex):
        return number(value)
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 2
    assert [(item.line, item.col) for item in diagnostics] == sorted(
        (item.line, item.col) for item in diagnostics
    )


def test_finds_valid_child_ladder_under_unrelated_outer_if() -> None:
    source = """
def parse(value: object):
    if ready:
        return cached()
    elif isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5


@pytest.mark.parametrize("source", ["", "# comment\n", "def f(:\n    pass"])
def test_trivial_or_invalid_source_is_ignored(source: str) -> None:
    assert _check(source) == []
