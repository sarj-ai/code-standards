"""SARJ031 — A nonzero `sleep()` directly in a `test_*` body is a flaky-test smell.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_sleep_in_test_body.py
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SLEEP_MODULES = frozenset({"asyncio", "time"})

type _SleepBindings = tuple[frozenset[str], frozenset[str]]


def _is_sleep_call(node: ast.Call, bindings: _SleepBindings) -> bool:
    module_names, direct_names = bindings
    func = node.func
    resolved = (
        isinstance(func, ast.Attribute)
        and func.attr == "sleep"
        and isinstance(func.value, ast.Name)
        and func.value.id in module_names
    ) or (isinstance(func, ast.Name) and func.id in direct_names)
    return resolved and len(node.args) >= 1 and _is_nonzero_numeric_literal(node.args[0])


def _resolved_sleep_bindings(
    owner: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    inherited: _SleepBindings = (frozenset(), frozenset()),
) -> _SleepBindings:
    """Resolve only unambiguous stdlib imports visible in `owner`."""
    module_names, direct_names = map(set, inherited)
    counts = _scope_binding_counts(owner)
    module_imports, function_imports = _direct_sleep_imports(owner.body)

    module_names.difference_update({name for name in module_names if counts[name]})
    direct_names.difference_update({name for name in direct_names if counts[name]})
    module_names.update(name for name, count in module_imports.items() if counts[name] == count)
    direct_names.update(name for name, count in function_imports.items() if counts[name] == count)
    return frozenset(module_names), frozenset(direct_names)


def _direct_sleep_imports(statements: list[ast.stmt]) -> tuple[Counter[str], Counter[str]]:
    """Count direct stdlib sleep bindings established unconditionally in a scope."""
    modules: Counter[str] = Counter()
    functions: Counter[str] = Counter()
    for statement in statements:
        match statement:
            case ast.Import(names=aliases):
                for alias in aliases:
                    if alias.name in _SLEEP_MODULES:
                        modules[alias.asname or alias.name] += 1
            case ast.ImportFrom(module=str() as module, level=0, names=aliases) if module in _SLEEP_MODULES:
                for alias in aliases:
                    if alias.name == "sleep":
                        functions[alias.asname or alias.name] += 1
            case _:
                pass
    return modules, functions


def _scope_binding_counts(owner: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> Counter[str]:
    """Count bindings in one lexical scope without entering nested definitions."""
    counts: Counter[str] = Counter()
    if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = owner.args
        for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
            if argument is not None:
                counts[argument.arg] += 1

    stack: list[ast.AST] = list(owner.body)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                counts[node.name] += 1
                continue
            case ast.Lambda():
                continue
            case ast.alias(name=name, asname=asname):
                counts[asname or name.split(".", maxsplit=1)[0]] += 1
            case ast.ExceptHandler(name=str() as name):
                counts[name] += 1
            case ast.MatchAs(name=str()) | ast.MatchStar(name=str()):
                if node.name is not None:
                    counts[node.name] += 1
            case ast.MatchMapping(rest=str() as rest):
                counts[rest] += 1
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                counts[name] += 1
            case _:
                pass
        stack.extend(ast.iter_child_nodes(node))
    return counts


def _is_nonzero_numeric_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and node.value != 0
    )


def _is_poll_loop(node: ast.For | ast.AsyncFor) -> bool:
    """Report whether a bounded `for` loop polls a condition rather than just waiting."""
    return any(_is_conditional_exit(stmt) for stmt in node.body)


def _is_conditional_exit(stmt: ast.stmt) -> bool:
    """Report whether `stmt` is an `if` that can leave the loop early."""
    return isinstance(stmt, ast.If) and any(
        isinstance(inner, (ast.Break, ast.Return, ast.Raise)) for inner in walk(stmt)
    )


@final
class NoSleepInTestBody(Rule):
    id: str = "no-sleep-in-test-body"
    code: str = "SARJ031"
    documentation = RuleDocumentation(
        summary="Tests should synchronize on observable state instead of waiting a fixed duration.",
        rationale="A fixed nonzero sleep makes test reliability and runtime depend on machine and CI timing.",
        remediation="Await the operation, wait on an event, or poll the expected condition with a bounded timeout.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test paths and calls resolved to imported `time.sleep` or `asyncio.sleep` are analyzed.",
            "Zero, computed, helper-owned, and bounded polling-loop sleeps are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="fixed-test-sleep",
                title="Test waits a fixed duration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_worker.py",
                        "import asyncio\n\nasync def test_worker_finishes():\n    start_worker()\n    await asyncio.sleep(0.1)\n    assert worker_finished()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_worker.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="event-synchronized-test",
                title="Test waits for the completion signal",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_worker.py",
                        "async def test_worker_finishes():\n    finished = start_worker()\n    await finished.wait()\n    assert worker_finished()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_worker.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        visitor = _SleepInTestBodyVisitor(_resolved_sleep_bindings(tree))
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

    def __init__(self, module_bindings: _SleepBindings) -> None:
        super().__init__()
        self._func_names: list[str | None] = []
        self._poll_depths: list[int] = []
        self._bindings: list[_SleepBindings] = [module_bindings]
        self.hits: list[ast.Call] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_names.append(node.name)
        self._poll_depths.append(0)
        self._bindings.append(_resolved_sleep_bindings(node, self._bindings[-1]))
        self.generic_visit(node)
        self._bindings.pop()
        self._poll_depths.pop()
        self._func_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._func_names.append(None)
        self._poll_depths.append(0)
        self._bindings.append(self._bindings[-1])
        self.generic_visit(node)
        self._bindings.pop()
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
        if self._func_names and _is_sleep_call(node, self._bindings[-1]):
            nearest = self._func_names[-1]
            in_poll_loop = bool(self._poll_depths and self._poll_depths[-1])
            if nearest is not None and nearest.startswith("test_") and not in_poll_loop:
                self.hits.append(node)
        self.generic_visit(node)
