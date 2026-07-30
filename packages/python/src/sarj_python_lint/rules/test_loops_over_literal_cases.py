"""SARJ041: a test looping over a literal case table is a hand-rolled parametrize.

`for payload in [a, b, c]: assert f(payload)` is `@pytest.mark.parametrize`
written by hand, and it loses everything the decorator provides. The loop is one
test to pytest, so it **stops at the first failing case** — a change that breaks
four of the six cases reports as a single failure and hides the blast radius.
The cases get no ids, so the run output names the loop's test, never the case.
And a case cannot be xfailed, skipped, or selected with `-k` individually.
Promoting the table to `@pytest.mark.parametrize` turns N hidden cases into N
independently reported tests for free.

Fires when ALL of these hold:

* the file is a test file, and the **nearest enclosing function** of the loop is
  named `test_*` — a loop inside a fixture or a local helper is building data,
  not enumerating cases, and the nearest-function check (the SARJ031 technique)
  excludes it automatically,
* the loop iterates a **literal** `list`, `tuple`, or `set` displayed inline at
  the loop header, holding at least two elements,
* the loop body contains an `assert` (at any depth inside the loop, but not
  inside a nested `def`),
* and the body does **not** open a sub-test context.

The literal-iterable requirement is the load-bearing false-positive guard, and
it is the entire difference between this rule and a naive "assert inside a for"
check. A blind sweep of both production corpora found 144 loops containing an
assert but only 48 iterating a literal; the 96-loop difference is dominated by
**exhaustiveness checks** — `for member in Language:`, `for name in ProbeName:`,
`for row in await store.list_calls():` — which iterate an enum, a fixture, or a
query result. Those express a single universal-quantifier behaviour ("every
member has a template"), not a table of independent cases; parametrizing them
would be wrong, and flagging them would have put this rule near a 67% false
positive rate.

Deliberately NOT flagged:

* `for i in range(n)` — a repetition count, not a case table. `range` is a call,
  so the literal check already excludes it,
* iteration over a name, attribute, comprehension, enum, or any call result —
  the cases are not visible at the loop header, so there is nothing to lift into
  a decorator,
* a single-element literal — no table to speak of,
* a literal loop whose body only builds state or calls the system under test
  with no assertion — that is setup, and setup legitimately loops,
* **a loop that wraps each iteration in a sub-test** — `with self.subTest(...)`
  (unittest) or `with subtests.test(...)` (the pytest-subtests plugin). Every
  complaint in the message above is already answered there: the loop does not
  stop at the first failure, and each iteration is reported under its own named
  sub-test. `black/tests/test_black.py:1699` and `:1719` iterate
  `["include", "force-exclude"]` inside `with self.subTest(config_key=...)`;
  both were third-party-sweep false positives.
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
    """A `for` over a literal case table with an assert inside — parametrize it."""

    id: str = "test-loops-over-literal-cases"
    code: str = "SARJ041"
    description: str = (
        "Test loops over a literal case table — use `@pytest.mark.parametrize` so cases report separately."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag literal-case loops that assert, directly inside a test function.

        Returns:
            One diagnostic per hand-rolled case-table loop, sorted by position.

        """
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
    """Flag literal-iterating, asserting loops whose nearest function is a test.

    Mirrors SARJ031's enclosing-function stack: only the innermost function is
    consulted, so a case loop inside a helper or fixture declared within a test
    is attributed to that helper and never fires.
    """

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
    # lifted into a decorator. Names, calls (`range`, `enumerate`), enums and
    # comprehensions all hide them, and are excluded by construction.
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
    # before the caller can reject it, so a nested `def` would leak its asserts
    # into this loop's result. Pruning the subtree requires not descending at all.
    # The scope test is applied to the node itself, not only to its children, so
    # a `def` sitting directly in the loop body is pruned too.
    if isinstance(node, _SCOPE_NODES):
        return False
    if isinstance(node, ast.Assert):
        return True
    return any(_contains_assert(child) for child in children(node))
