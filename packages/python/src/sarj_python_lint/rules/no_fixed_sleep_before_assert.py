from __future__ import annotations

import ast
from itertools import pairwise
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, Final, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_ASYNC_SLEEPS: Final = frozenset({"asyncio.sleep", "anyio.sleep", "trio.sleep"})
_DURATION_KEYWORDS: Final = frozenset({"delay", "seconds"})
_CONSTANT_NAME: Final = re.compile(r"_*[A-Z][A-Z0-9_]*")
_MESSAGE: Final = (
    "fixed sleep before an assertion guesses how long the code under test needs; await its signal or poll "
    "the condition with a deadline"
)

type _TestFunction = ast.FunctionDef | ast.AsyncFunctionDef


@final
class NoFixedSleepBeforeAssert(Rule):
    id = "no-fixed-sleep-before-assert"
    code = "SARJ455"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not sleep for a fixed interval and then assert in a test.",
        rationale=(
            "A fixed sleep followed by an assertion guesses how long the code under test needs. On a loaded CI "
            "runner the guess is too short and the test flakes; on an idle one every run pays the whole interval."
        ),
        remediation=(
            "Await the signal the code exposes, such as an event, future, queue item, or fake callback, or poll the "
            "condition with a deadline. When the test deliberately proves that nothing happens during a quiet "
            "window, keep the sleep with an exact SARJ455 suppression that names the window."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only pytest-collected test functions in test_*.py and *_test.py modules are inspected; fixtures, helpers, nested functions, and conftest.py are not.",
            "A sleep is reported only when the next statement in the same block is an assert, so an assert placed after the enclosing with, if, or try block is not reported.",
            "A duration is fixed only when built from numeric literals and UPPER_CASE constants; durations read from other names or from calls are not reported.",
            "Sleeps inside loops are treated as polling, and time.sleep in an async test is left to Ruff ASYNC251.",
        ),
        examples=(
            RuleExample(
                example_id="test-sleeps-then-asserts",
                title="A test waits a guessed interval before asserting",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_monitor.py",
                        "import asyncio\n\n\nasync def test_reports_silence(monitor):\n    monitor.start()\n"
                        "    await asyncio.sleep(0.5)\n    assert monitor.reason == 'silence'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_monitor.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="test-awaits-signal-then-asserts",
                title="A test awaits the signal with a deadline before asserting",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_monitor.py",
                        "import asyncio\n\n\nasync def test_reports_silence(monitor):\n    monitor.start()\n"
                        "    await asyncio.wait_for(monitor.fired.wait(), timeout=5)\n"
                        "    assert monitor.reason == 'silence'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_monitor.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="test-blocks-then-asserts",
                title="A synchronous test blocks for a guessed interval before asserting",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_worker.py",
                        "import time\n\n\ndef test_worker_drains_queue(worker, queue):\n    worker.start()\n"
                        "    time.sleep(1)\n    assert queue.pending() == 0\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_worker.py"),
                expected_count=1,
                scenario="blocking-sleep",
                public=True,
            ),
            RuleExample(
                example_id="test-polls-with-deadline-then-asserts",
                title="A synchronous test polls the condition with a deadline before asserting",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_worker.py",
                        "import time\n\n\ndef test_worker_drains_queue(worker, queue):\n    worker.start()\n"
                        "    deadline = time.monotonic() + 5\n"
                        "    while queue.pending() and time.monotonic() < deadline:\n        time.sleep(0.01)\n"
                        "    assert queue.pending() == 0\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_worker.py"),
                expected_count=0,
                scenario="blocking-sleep",
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if not _is_collected_test_module(path) or "sleep" not in source or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        imports = context.imports
        diagnostics = [
            Diagnostic(path=path, line=statement.lineno, col=statement.col_offset + 1, code=self.code, message=_MESSAGE)
            for test in _collected_tests(tree.body)
            for statement, following in _adjacent_statements(test.body)
            if isinstance(following, ast.Assert) and _is_fixed_sleep(statement, test, imports)
        ]
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _is_collected_test_module(path: Path) -> bool:
    return path.suffix == ".py" and (path.stem.startswith("test_") or path.stem.endswith("_test"))


def _collected_tests(statements: list[ast.stmt]) -> Iterator[_TestFunction]:
    for statement in statements:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() if statement.name.startswith("test"):
                yield statement
            case ast.ClassDef() if statement.name.startswith("Test"):
                yield from _collected_tests(statement.body)
            case _:
                pass


def _adjacent_statements(block: list[ast.stmt]) -> Iterator[tuple[ast.stmt, ast.stmt]]:
    yield from pairwise(block)
    for statement in block:
        for nested in _straight_line_blocks(statement):
            yield from _adjacent_statements(nested)


def _straight_line_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    match statement:
        case ast.If(body=body, orelse=orelse):
            return [body, orelse]
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return [body]
        case (
            ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
            | ast.TryStar(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
        ):
            return [body, *(handler.body for handler in handlers), orelse, finalbody]
        case ast.Match(cases=cases):
            return [case.body for case in cases]
        case _:
            return []


def _is_fixed_sleep(statement: ast.stmt, test: _TestFunction, imports: ImportIndex) -> bool:
    match statement:
        case ast.Expr(value=ast.Await(value=ast.Call() as call)):
            return imports.resolved_qualified_name(call.func) in _ASYNC_SLEEPS and _has_fixed_duration(call)
        case ast.Expr(value=ast.Call() as call) if isinstance(test, ast.FunctionDef):
            return imports.resolved_qualified_name(call.func) == "time.sleep" and _has_fixed_duration(call)
        case _:
            return False


def _has_fixed_duration(call: ast.Call) -> bool:
    duration = (
        call.args[0]
        if call.args
        else next((keyword.value for keyword in call.keywords if keyword.arg in _DURATION_KEYWORDS), None)
    )
    match duration:
        case None | ast.Constant(value=0):
            return False
        case _:
            return _is_fixed(duration)


def _is_fixed(node: ast.expr) -> bool:
    match node:
        case ast.Constant(value=int() | float()):
            return True
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return _CONSTANT_NAME.fullmatch(name) is not None
        case ast.UnaryOp(op=ast.UAdd() | ast.USub(), operand=operand):
            return _is_fixed(operand)
        case ast.BinOp(left=left, op=ast.Add() | ast.Sub() | ast.Mult() | ast.Div() | ast.FloorDiv(), right=right):
            return _is_fixed(left) and _is_fixed(right)
        case _:
            return False
