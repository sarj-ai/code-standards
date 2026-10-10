from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, Final, NamedTuple, final, override

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
    is_suppressed,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext


_ASYNC_SLEEPS: Final = frozenset({"asyncio.sleep", "anyio.sleep", "trio.sleep"})
_BLOCKING_SLEEP: Final = "time.sleep"
_DURATION_KEYWORDS: Final = frozenset({"delay", "seconds"})
_CONSTANT_NAME: Final = re.compile(r"_*[A-Z][A-Z0-9_]*")
_LOOPS: Final = (ast.For, ast.AsyncFor, ast.While)
_FUNCTIONS: Final = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPES: Final = (*_FUNCTIONS, ast.Lambda, ast.ClassDef)
_MESSAGE: Final = (
    "fixed sleep inside a loop makes every iteration wait on the wall clock, including under test; take the "
    "interval or the sleeper from an injected dependency"
)


@final
class NoFixedSleepInLoop(Rule):
    id = "no-fixed-sleep-in-loop"
    code = "SARJ485"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not sleep for a fixed literal interval inside a production loop.",
        rationale=(
            "A polling or cleanup loop that sleeps for a literal interval gives tests no seam: every test that "
            "drives the loop pays the whole interval in real time, and replacing the module's sleep is a "
            "monkeypatch that SARJ445 forbids. Suites slow down one hardcoded interval at a time."
        ),
        remediation=(
            "Route the interval through a constructor or configuration parameter, or call an injected sleeper or "
            "clock, so tests can pass a zero interval or a recording fake. Keep a literal only behind an exact "
            "SARJ485 suppression that names why the interval must never change under test."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only awaited asyncio.sleep, anyio.sleep, and trio.sleep, and time.sleep in synchronous functions, are inspected; import aliases are followed and shadowed names abstain. time.sleep in an async function is left to Ruff ASYNC251.",
            "A duration is fixed when it folds with +, -, *, /, and // from numeric literals and UPPER_CASE constants bound once at module scope in the same file to such a literal; zero and negative results are yields, not waits.",
            "Imported, reassigned, or shadowed constants, lowercase names, attributes including class constants, subscripts, and calls are treated as configurable and are not reported.",
            "The sleep must sit in the body of a for, async for, or while loop inside the same function; loop else clauses, module-level and class-level loops, and loops in an enclosing function across a nested def, lambda, or class are not reported.",
            "Test modules, test directories, conftest.py, test-support paths, and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="polling-loop-sleeps-literal",
                title="A polling loop sleeps for a hardcoded interval",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/jobs.py",
                        "import asyncio\n\n\nasync def wait_until_done(job):\n    while not await job.done():\n"
                        "        await asyncio.sleep(2)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/jobs.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="polling-loop-sleeps-injected-interval",
                title="A polling loop sleeps for an injected interval",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/jobs.py",
                        "import asyncio\n\n\nclass JobWaiter:\n    def __init__(self, poll_seconds: float) -> None:\n"
                        "        self._poll_seconds = poll_seconds\n\n    async def wait_until_done(self, job):\n"
                        "        while not await job.done():\n            await asyncio.sleep(self._poll_seconds)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/jobs.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="blocking-loop-sleeps-literal",
                title="A synchronous retry loop blocks for a hardcoded interval",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/health.py",
                        "import time\n\n\ndef wait_for_health(probe):\n    for _ in range(30):\n"
                        "        if probe():\n            return\n        time.sleep(0.5)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/health.py"),
                expected_count=1,
                scenario="blocking-sleep",
                public=True,
            ),
            RuleExample(
                example_id="blocking-loop-calls-injected-sleeper",
                title="A synchronous retry loop calls an injected sleeper",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/health.py",
                        "from collections.abc import Callable\n\n\n"
                        "def wait_for_health(probe, sleep: Callable[[float], None]):\n    for _ in range(30):\n"
                        "        if probe():\n            return\n        sleep(0.5)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/health.py"),
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
        if (
            "sleep" not in context.symbol_source
            or is_test_path(path)
            or is_test_support_path(path)
            or context.generated
            or context.tree is None
        ):
            return []
        sleeps = [
            sleep
            for call in context.nodes(ast.Call)
            if (sleep := _sleep(context, call)) is not None and _in_function_loop_body(context, sleep.reported)
        ]
        if not sleeps:
            return []
        constants = _module_constants(context)
        findings = [
            Diagnostic(
                path=path,
                line=reported.lineno,
                col=reported.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
                severity=Severity.WARNING,
            )
            for reported, duration in sleeps
            if (seconds := _folded_seconds(duration, constants)) is not None
            and seconds > 0
            and not is_suppressed(context.source_lines, reported.lineno, self.code)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


class _Sleep(NamedTuple):
    reported: ast.expr
    duration: ast.expr | None


def _sleep(context: PythonFileContext, call: ast.Call) -> _Sleep | None:
    name = context.imports.resolved_qualified_name(call.func)
    parent = context.parents.get(call)
    if name in _ASYNC_SLEEPS and isinstance(parent, ast.Await):
        return _Sleep(parent, _duration(call))
    if name == _BLOCKING_SLEEP and isinstance(_owner(context, call), ast.FunctionDef):
        return _Sleep(call, _duration(call))
    return None


def _duration(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    return next((keyword.value for keyword in call.keywords if keyword.arg in _DURATION_KEYWORDS), None)


def _module_constants(context: PythonFileContext) -> dict[str, float]:
    tree = context.tree
    if tree is None:
        return {}
    assignments: dict[str, ast.expr] = {}
    for statement in tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ) if _CONSTANT_NAME.fullmatch(name):
                assignments[name] = value
            case _:
                pass
    stores = Counter(node.id for node in context.nodes(ast.Name) if not isinstance(node.ctx, ast.Load))
    rebound = {
        *(node.arg for node in context.nodes(ast.arg)),
        *(name for node in context.nodes(ast.Global, ast.Nonlocal) for name in node.names),
        *(node.name for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)),
        *context.imports.bindings,
    }
    return {
        name: seconds
        for name, value in assignments.items()
        if stores[name] == 1 and name not in rebound and (seconds := _folded_seconds(value, {})) is not None
    }


def _folded_seconds(node: ast.expr | None, constants: Mapping[str, float]) -> float | None:
    match node:
        case ast.Constant(value=bool()):
            return None
        case ast.Constant(value=int() | float() as value):
            return value
        case ast.Name(id=name):
            return constants.get(name)
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _folded_seconds(operand, constants)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            value = _folded_seconds(operand, constants)
            return None if value is None else -value
        case ast.BinOp(left=left, op=op, right=right):
            lhs, rhs = _folded_seconds(left, constants), _folded_seconds(right, constants)
            return None if lhs is None or rhs is None else _arithmetic(op, lhs, rhs)
        case _:
            return None


def _arithmetic(op: ast.operator, lhs: float, rhs: float) -> float | None:
    match op:
        case ast.Add():
            return lhs + rhs
        case ast.Sub():
            return lhs - rhs
        case ast.Mult():
            return lhs * rhs
        case ast.Div() if rhs:
            return lhs / rhs
        case ast.FloorDiv() if rhs:
            return lhs // rhs
        case _:
            return None


def _owner(context: PythonFileContext, node: ast.AST) -> ast.AST | None:
    current = context.parents.get(node)
    while current is not None and not isinstance(current, _SCOPES):
        current = context.parents.get(current)
    return current


def _in_function_loop_body(context: PythonFileContext, node: ast.AST) -> bool:
    in_loop = False
    child, parent = node, context.parents.get(node)
    while parent is not None and not isinstance(parent, _SCOPES):
        if isinstance(parent, _LOOPS) and any(statement is child for statement in parent.body):
            in_loop = True
        child, parent = parent, context.parents.get(parent)
    return in_loop and isinstance(parent, _FUNCTIONS)
