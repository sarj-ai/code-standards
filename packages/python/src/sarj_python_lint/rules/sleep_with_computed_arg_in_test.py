"""SARJ047 — `sleep(POLL_INTERVAL * 4)` in a test is the same race SARJ031 bans.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_sleep_with_computed_arg_in_test.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SLEEP_RECEIVERS = frozenset({"asyncio", "time"})


class SleepWithComputedArgInTest(Rule):
    id: str = "sleep-with-computed-arg-in-test"
    code: str = "SARJ047"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Computed `sleep()` in a test body — synchronize on the signal, don't guess a delay.",
        rationale="A calculated delay still races the system under load and makes test duration depend on guessed timing.",
        remediation="Await completion, wait on an event, or poll the expected condition with a bounded deadline.",
        category=RuleCategory.TESTING,
        limitations=(
            "Only `time.sleep` and `asyncio.sleep` calls directly inside test functions are analyzed.",
            "Numeric literal delays belong to SARJ031; helper-owned and nested-function sleeps are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="computed-test-sleep",
                title="Test guesses a computed delay",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_worker.py",
                        "import asyncio\n\nasync def test_worker():\n    await asyncio.sleep(POLL_INTERVAL * 4)\n    assert finished()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_worker.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="event-synchronized-test",
                title="Test waits for completion",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_worker.py",
                        "async def test_worker():\n    finished = start_worker()\n    await finished.wait()\n    assert finished.is_set()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_worker.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag non-literal `sleep()` delays sitting directly in a test body."""
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
    """Flag computed-delay sleeps whose NEAREST enclosing function is a test."""

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
