"""SARJ041 — A test looping over a literal case table is a hand-rolled parametrize.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_test_loops_over_literal_cases.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_LITERAL_ITERABLES = (ast.List, ast.Tuple, ast.Set)

_MIN_CASES = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Anything that opens a new function scope: an assert inside one belongs to it.
_SCOPE_NODES = (*_FUNC_NODES, ast.Lambda)

# `self.subTest(...)` (unittest) and `subtests.test(...)` (pytest-subtests):
# each iteration already reports independently and a failure does not abort the
# loop, which is exactly what this rule asks parametrize to provide.
_SUBTEST_ATTRS = frozenset({"subTest", "subtest"})

_SUBTESTS_FIXTURE = "subtests"


class TestLoopsOverLiteralCases(Rule):
    id: str = "test-loops-over-literal-cases"
    code: str = "SARJ041"
    description: str = (
        "Test loops over a literal case table — use `@pytest.mark.parametrize` so cases report separately."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag literal-case loops that assert, directly inside a test function."""
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _LiteralCaseLoopVisitor()
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this loop asserts over {count} inline cases — pytest sees one test, so it stops "
                    "at the first failure and never names the failing case. Lift the table into "
                    "`@pytest.mark.parametrize` to get one reported test per case."
                ),
            )
            for node, count in visitor.hits
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _LiteralCaseLoopVisitor(ast.NodeVisitor):
    """Flag literal-iterating, asserting loops whose nearest function is a test."""

    def __init__(self) -> None:
        super().__init__()
        self._func_names: list[str | None] = []
        self.hits: list[tuple[ast.For | ast.AsyncFor, int]] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_names.append(node.name)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._func_names.append(None)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_For(self, node: ast.For) -> None:
        self._check_loop(node)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._check_loop(node)
        self.generic_visit(node)

    def _check_loop(self, node: ast.For | ast.AsyncFor) -> None:
        if not self._in_test_function():
            return
        count = _literal_case_count(node.iter)
        if count < _MIN_CASES or not _body_asserts(node) or _body_opens_a_subtest(node):
            return
        self.hits.append((node, count))

    def _in_test_function(self) -> bool:
        nearest = self._func_names[-1] if self._func_names else None
        return nearest is not None and nearest.startswith("test_")


def _literal_case_count(iterable: ast.expr) -> int:
    # Only a display literal at the loop header exposes cases that could be
    if not isinstance(iterable, _LITERAL_ITERABLES):
        return 0
    if any(isinstance(elt, ast.Starred) for elt in iterable.elts):
        return 0
    return len(iterable.elts)


def _body_asserts(node: ast.For | ast.AsyncFor) -> bool:
    return any(_contains_assert(stmt) for stmt in node.body)


def _body_opens_a_subtest(node: ast.For | ast.AsyncFor) -> bool:
    return any(
        isinstance(child, (ast.With, ast.AsyncWith))
        and any(_is_subtest_call(item.context_expr) for item in child.items)
        for stmt in node.body
        for child in walk(stmt)
    )


def _is_subtest_call(expr: ast.expr) -> bool:
    if not isinstance(expr, ast.Call) or not isinstance(expr.func, ast.Attribute):
        return False
    attr = expr.func
    if attr.attr in _SUBTEST_ATTRS:
        return True
    return attr.attr == "test" and isinstance(attr.value, ast.Name) and attr.value.id == _SUBTESTS_FIXTURE


def _contains_assert(node: ast.AST) -> bool:
    # Hand-rolled descent rather than `ast.walk`: walk enqueues a node's children
    if isinstance(node, _SCOPE_NODES):
        return False
    if isinstance(node, ast.Assert):
        return True
    return any(_contains_assert(child) for child in children(node))
