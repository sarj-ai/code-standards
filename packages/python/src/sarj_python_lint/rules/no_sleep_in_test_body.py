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

A sleep inside a `while` loop is also exempt: `while not cond: time.sleep(0.01)`
is condition-polling — exactly the remedy this rule's own message prescribes
(trio's OS-thread waits were the sweep case). Only a bare fixed delay flakes.

A bounded `for` retry loop that exits early on the condition is the same remedy
with a deadline attached, so it is exempt too:

    for _ in range(20):
        if started.is_set():
            break
        await asyncio.sleep(0.01)

The `for` must carry that conditional exit (an `if` whose body `break`s /
`return`s / `raise`s); a `for` that merely repeats a fixed delay each iteration
is not polling and still fires. Found in a 2,657-file third-party sweep against
anyio's `test_from_thread.py` (`for _ in range(10): if ...: return; sleep(0.1)`)
and black's `test_blackd.py` (`for _ in range(20): if started.is_set(): break;
await asyncio.sleep(0.01)`) — both poll with a timeout and neither can flake the
way a bare delay does.

Applies only in test files (stem `test_*.py`, `*_test.py`, `conftest.py`, or a path
under a `tests`/`test` directory).
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import walk
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


def _is_conditional_exit(stmt: ast.stmt) -> bool:
    """Report whether `stmt` is an `if` that can leave the loop early.

    Returns:
        True for an `if` whose body diverts via `break` / `return` / `raise`.

    """
    return isinstance(stmt, ast.If) and any(
        isinstance(inner, (ast.Break, ast.Return, ast.Raise)) for inner in walk(stmt)
    )


def _is_poll_loop(node: ast.For | ast.AsyncFor) -> bool:
    """Report whether a bounded `for` loop polls a condition rather than just waiting.

    `for _ in range(20): if ready(): break; sleep(0.01)` is condition-polling with
    a deadline — the remedy this rule prescribes — so its sleep is not a flake.
    A `for` body with no conditional exit merely repeats a fixed delay and is not
    polling.

    Returns:
        True when the loop body carries a conditional early exit.

    """
    return any(_is_conditional_exit(stmt) for stmt in node.body)


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
        self._poll_depths: list[int] = []
        self.hits: list[ast.Call] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_names.append(node.name)
        self._poll_depths.append(0)
        self.generic_visit(node)
        self._poll_depths.pop()
        self._func_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._func_names.append(None)
        self._poll_depths.append(0)
        self.generic_visit(node)
        self._poll_depths.pop()
        self._func_names.pop()

    def _visit_poll_loop(self, node: ast.AST) -> None:
        if self._poll_depths:
            self._poll_depths[-1] += 1
        self.generic_visit(node)
        if self._poll_depths:
            self._poll_depths[-1] -= 1

    def visit_While(self, node: ast.While) -> None:
        # `while not cond: sleep(...)` is condition-polling — the remedy, not
        # the flake — so sleeps under a while in the current function are exempt.
        self._visit_poll_loop(node)

    def visit_For(self, node: ast.For) -> None:
        # A bounded retry loop that exits early on the condition is the same
        # polling remedy with a deadline; a `for` that only repeats a delay is not.
        if _is_poll_loop(node):
            self._visit_poll_loop(node)
        else:
            self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        if _is_poll_loop(node):
            self._visit_poll_loop(node)
        else:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._func_names and _is_sleep_call(node):
            nearest = self._func_names[-1]
            in_poll_loop = bool(self._poll_depths and self._poll_depths[-1])
            if nearest is not None and nearest.startswith("test_") and not in_poll_loop:
                self.hits.append(node)
        self.generic_visit(node)
