"""SARJ031 — A nonzero `sleep()` directly in a `test_*` body is a flaky-test smell.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_sleep_in_test_body.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ031.md
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
    """Report whether `stmt` is an `if` that can leave the loop early."""
    return isinstance(stmt, ast.If) and any(
        isinstance(inner, (ast.Break, ast.Return, ast.Raise)) for inner in walk(stmt)
    )


def _is_poll_loop(node: ast.For | ast.AsyncFor) -> bool:
    """Report whether a bounded `for` loop polls a condition rather than just waiting."""
    return any(_is_conditional_exit(stmt) for stmt in node.body)


class NoSleepInTestBody(Rule):
    id: str = "no-sleep-in-test-body"
    code: str = "SARJ031"
    has_evidence: bool = True
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
    """Flag sleep calls whose NEAREST enclosing function is a `test_*` def."""

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
