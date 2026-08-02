"""SARJ045 — A domain object built with many kwargs inline belongs in a builder.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_kwarg_heavy_construction_in_test.py
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MAX_KEYWORDS = 8

# A builder only pays for itself once the same callee is built more than once.
_MIN_CONSTRUCTIONS = 2

# `dict(a=1, b=2, ...)` is a mapping literal, not a domain object.
_DATA_CALLABLES = frozenset({"dict"})

# `<mapping>.update(a=1, b=2, ...)` spreads mapping entries — data again, and no
# object a builder could construct.
_DATA_METHODS = frozenset({"update"})

# `mock.assert_called_once_with(a=1, ...)` builds nothing: it pins the exact call
# the code under test made, so defaulting its keywords away deletes the assertion.
_MOCK_ASSERTION_PREFIX = "assert_"


class KwargHeavyConstructionInTest(Rule):
    id: str = "kwarg-heavy-construction-in-test"
    code: str = "SARJ045"
    description: str = "Object built with many keywords inline in a test — extract a helper with defaults."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag kwarg-heavy constructions sitting directly in a test body."""
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _KwargHeavyVisitor()
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this call passes {count} keywords inline, so the one field under test is buried "
                    "and every other test repeats the same boilerplate. Extract a helper with "
                    "defaults and override only what this test is about."
                ),
            )
            for node, count in visitor.reportable_hits(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _KwargHeavyVisitor(ast.NodeVisitor):
    """Flag wide keyword calls whose nearest enclosing function is a test."""

    def __init__(self) -> None:
        super().__init__()
        self._func_names: list[str | None] = []
        self.hits: list[tuple[ast.Call, int]] = []

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

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_test_function() and not _is_data_callable(node.func) and not _is_mock_assertion(node.func):
            named = [kw for kw in node.keywords if kw.arg is not None]
            if len(named) > _MAX_KEYWORDS:
                self.hits.append((node, len(named)))
        self.generic_visit(node)

    def reportable_hits(self, tree: ast.Module) -> list[tuple[ast.Call, int]]:
        """Keep repeated calls unless their callee is a helper defined here."""
        counts = Counter(name for n in nodes(tree, ast.Call) if (name := _callee_name(n.func)) is not None)
        local_defs = _locally_defined_names(tree)
        return [
            (node, count)
            for node, count in self.hits
            # A callee with no stable name (a subscript, a call result) cannot be
            # counted, so it can never clear the repetition bar.
            if (name := _callee_name(node.func)) is not None
            and counts[name] >= _MIN_CONSTRUCTIONS
            and not _calls_a_local_helper(node.func, local_defs)
        ]

    def _in_test_function(self) -> bool:
        nearest = self._func_names[-1] if self._func_names else None
        return nearest is not None and nearest.startswith("test_")


def _is_data_callable(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _DATA_CALLABLES
    return isinstance(func, ast.Attribute) and func.attr in _DATA_METHODS


def _is_mock_assertion(func: ast.expr) -> bool:
    """Return whether the call asserts on a mock instead of building an object."""
    name = _callee_name(func)
    return name is not None and name.startswith(_MOCK_ASSERTION_PREFIX)


def _locally_defined_names(tree: ast.Module) -> frozenset[str]:
    """Collect names bound by functions defined in this module."""
    return frozenset(node.name for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef))


def _calls_a_local_helper(func: ast.expr, local_defs: frozenset[str]) -> bool:
    """Return whether a bare callee names a function defined in this module."""
    return isinstance(func, ast.Name) and func.id in local_defs


def _callee_name(func: ast.expr) -> str | None:
    """Render the callee as a comparable name, so repeats can be counted."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None
