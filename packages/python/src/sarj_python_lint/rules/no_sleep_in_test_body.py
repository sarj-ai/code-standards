"""SARJ031: a nonzero `sleep()` directly in a `test_*` body is a flaky-test smell.

`asyncio.sleep(0.01)` / `time.sleep(1)` placed straight in a test function body is
the canonical flaky-test pattern: under CI load the fixed delay is nondeterministic
(too short → the awaited work has not finished; the test flakes), and it slows the
suite for no benefit. The fix is to synchronize on the actual signal — await the
awaitable, wait on an `Event`, or poll a condition with a timeout.

This is test-scoped and genuinely uncovered: ruff ASYNC251 only flags blocking
`time.sleep` inside an `async def`, and nothing flags `asyncio.sleep(nonzero)`.

Fires only on the exact shape:

* a call `asyncio.sleep(<arg>)` or `time.sleep(<arg>)` (receiver is the bare name
  `asyncio` or `time`),
* where `<arg>` is a **nonzero numeric literal** (`int`/`float` `ast.Constant`) —
  `sleep(0)` is a cooperative yield, not a timing hack, and a non-literal
  `sleep(delay)` is a deliberate configured wait, so both are skipped, and
* whose **nearest enclosing function is a `test_*`-named** `def`/`async def`.

Critical false-positive guard: the sleep must sit DIRECTLY in the test body, with
no intervening nested `def`/`async def`/`lambda`. A sleep inside a nested helper /
fake coroutine declared within the test (`_hang`, `_slow`, `mock_*`) deliberately
simulates latency to exercise cancellation/timeout paths — that is the intended
use, not a flaky sync, and it must not fire. Because the check keys off the
*nearest* enclosing function, such a nested helper (not `test_*`-named) is excluded
automatically.

Applies only in test files (stem `test_*.py`, `*_test.py`, `conftest.py`, or a path
under a `tests`/`test` directory).
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SLEEP_RECEIVERS = frozenset({"asyncio", "time"})


def _is_nonzero_numeric_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and node.value != 0
    )


def _is_sleep_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "sleep"
        and isinstance(func.value, ast.Name)
        and func.value.id in _SLEEP_RECEIVERS
        and len(node.args) >= 1
        and _is_nonzero_numeric_literal(node.args[0])
    )


class NoSleepInTestBody(Rule):
    """Nonzero `sleep()` directly in a `test_*` body — flaky timing sync."""

    id: str = "no-sleep-in-test-body"
    code: str = "SARJ031"
    description: str = "Nonzero `sleep()` in a test body — synchronize on the signal, don't sleep."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        visitor = _SleepInTestBodyVisitor()
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    "nonzero `sleep()` directly in a test body flakes under CI load — "
                    "await the awaitable, wait on an `Event`, or poll the condition instead."
                ),
            )
            for node in visitor.hits
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _SleepInTestBodyVisitor(ast.NodeVisitor):
    """Flag sleep calls whose NEAREST enclosing function is a `test_*` def.

    Maintains a stack of enclosing-function names (`None` for a lambda, which has
    no name and can never be a test). Only the top of the stack — the nearest
    enclosing function — is consulted, so a sleep inside a nested helper/fake
    coroutine declared within a test is attributed to that helper, not the test,
    and does not fire.
    """

    def __init__(self) -> None:
        super().__init__()
        self._func_names: list[str | None] = []
        self.hits: list[ast.Call] = []

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
        if self._func_names and _is_sleep_call(node):
            nearest = self._func_names[-1]
            if nearest is not None and nearest.startswith("test_"):
                self.hits.append(node)
        self.generic_visit(node)
