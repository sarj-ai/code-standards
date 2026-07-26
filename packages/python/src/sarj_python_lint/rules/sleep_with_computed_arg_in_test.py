"""SARJ047: `sleep(POLL_INTERVAL * 4)` in a test is the same race SARJ031 bans.

SARJ031 flags a nonzero *literal* `sleep()` in a test body and deliberately
exempts a computed argument, on the reasoning that `sleep(delay)` is a
configured wait passed in by the caller. That reasoning holds for a fixture or a
helper. It does not hold when the nearest enclosing function is the test itself:
`await asyncio.sleep(POLL_INTERVAL_SECONDS * 4)` is not configuration, it is a
hand-tuned guess that four poll intervals is "probably enough" for a background
task to progress. Under CI load it is the same nondeterministic race, with the
same fix — synchronise on the signal, wait on an `Event`, or poll the condition
with a deadline.

This rule closes exactly that gap and nothing more. Where SARJ031 requires a
nonzero numeric literal, this one requires an argument that is *not* a literal —
a name, attribute, arithmetic expression, or call. The two are disjoint by
construction, so no `sleep()` is ever reported twice.

Fires when ALL of these hold:

* the file is a test file,
* the call is `asyncio.sleep(...)` or `time.sleep(...)` (receiver is the bare
  name `asyncio` or `time`, matching SARJ031's shape),
* the first argument is not a numeric literal — SARJ031 owns that case,
* and the **nearest enclosing function** is named `test_*`.

The nearest-enclosing-function stack is inherited verbatim from SARJ031 and is
the critical guard. A `sleep(delay)` inside a nested fake coroutine declared in
the test (`_hang`, `_slow`, `mock_*`) deliberately simulates latency to exercise
a cancellation or timeout path — that is the intended use of a configured wait,
and because the check keys off the *nearest* function, such a helper is excluded
automatically.

Deliberately NOT flagged:

* `sleep(0)` and other numeric literals — SARJ031's territory,
* a computed `sleep()` in a fixture, helper, or any non-test function — the
  configured-wait reading applies there,
* `sleep()` reached through an aliased import (`from asyncio import sleep`) —
  the attribute-receiver shape is shared with SARJ031 so the two rules stay
  aligned, and a sweep of both corpora found zero occurrences of the bare-import
  spelling to justify widening it.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SLEEP_RECEIVERS = frozenset({"asyncio", "time"})


class SleepWithComputedArgInTest(Rule):
    """A computed-delay `sleep()` in a test body is a hand-tuned race."""

    id: str = "sleep-with-computed-arg-in-test"
    code: str = "SARJ047"
    description: str = "Computed `sleep()` in a test body — synchronize on the signal, don't guess a delay."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag non-literal `sleep()` delays sitting directly in a test body.

        Returns:
            One diagnostic per computed-delay sleep, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _ComputedSleepVisitor()
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    "this `sleep()` delay is computed in the test body — it is a guess at how long the "
                    "work takes, and it races under CI load exactly like a literal one. Await the "
                    "awaitable, wait on an `Event`, or poll the condition with a deadline."
                ),
            )
            for node in visitor.hits
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _ComputedSleepVisitor(ast.NodeVisitor):
    """Flag computed-delay sleeps whose NEAREST enclosing function is a test.

    The stack is SARJ031's, unchanged: a `None` entry for a lambda, and only the
    top consulted, so a configured wait inside a nested fake coroutine is
    attributed to that coroutine and never fires.
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
        if self._in_test_function() and _is_computed_sleep(node):
            self.hits.append(node)
        self.generic_visit(node)

    def _in_test_function(self) -> bool:
        nearest = self._func_names[-1] if self._func_names else None
        return nearest is not None and nearest.startswith("test_")


def _is_computed_sleep(node: ast.Call) -> bool:
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr == "sleep"
        and isinstance(func.value, ast.Name)
        and func.value.id in _SLEEP_RECEIVERS
        and node.args
    ):
        return False
    return not _is_numeric_literal(node.args[0])


def _is_numeric_literal(node: ast.expr) -> bool:
    # Literals belong to SARJ031; keeping the two predicates disjoint means a
    # single sleep is never reported by both rules.
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
