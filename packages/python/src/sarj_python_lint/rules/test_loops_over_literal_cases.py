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
_UNITTEST_SUBTEST = "subTest"

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
        self._functions: list[ast.FunctionDef | ast.AsyncFunctionDef | None] = []
        self.hits: list[tuple[ast.For | ast.AsyncFor, int]] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._functions.append(node)
        self.generic_visit(node)
        self._functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._functions.append(None)
        self.generic_visit(node)
        self._functions.pop()

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
        if (
            count < _MIN_CASES
            or not _body_asserts(node)
            or _body_opens_a_subtest(node)
            or self._followed_by_assertion(node)
        ):
            return
        self.hits.append((node, count))

    def _in_test_function(self) -> bool:
        nearest = self._functions[-1] if self._functions else None
        return nearest is not None and nearest.name.startswith("test_")

    def _followed_by_assertion(self, node: ast.For | ast.AsyncFor) -> bool:
        """Protect state-building loops whose aggregate contract follows the loop."""
        owner = self._functions[-1] if self._functions else None
        if owner is None:
            return False
        for index, stmt in enumerate(owner.body):
            if stmt is node:
                return any(_is_assertion_statement(later) for later in owner.body[index + 1 :])
        return False


def _literal_case_count(iterable: ast.expr) -> int:
    # Only display literals expose a case table that can move into parametrize.
    match iterable:
        case ast.Call(func=ast.Attribute(value=ast.Dict(keys=keys), attr=view), args=[], keywords=[]) if view in {
            "items",
            "keys",
            "values",
        }:
            return 0 if any(key is None for key in keys) else len(keys)
        case _:
            pass
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
    if attr.attr == _UNITTEST_SUBTEST:
        return isinstance(attr.value, ast.Name) and attr.value.id == "self"
    return attr.attr == "test" and isinstance(attr.value, ast.Name) and attr.value.id == _SUBTESTS_FIXTURE


def _contains_assert(node: ast.AST) -> bool:
    # Prune nested scopes explicitly because ast.walk cannot stop after enqueueing their children.
    if isinstance(node, _SCOPE_NODES):
        return False
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call) and _is_verification_call(node):
        return True
    return any(_contains_assert(child) for child in children(node))


def _is_verification_call(node: ast.Call) -> bool:
    """Recognise the two assertion APIs whose semantics are unambiguous."""
    func = node.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return False
    if func.value.id == "self" and func.attr.startswith("assert"):
        return True
    return func.value.id == "pytest" and func.attr in {"raises", "warns"}


def _is_assertion_statement(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assert):
        return True
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _is_verification_call(node.value)
