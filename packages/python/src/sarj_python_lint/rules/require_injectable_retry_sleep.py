from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
    is_suppressed,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_POLICIES: Final = frozenset(
    {"tenacity.retry", "tenacity.Retrying", "tenacity.AsyncRetrying", "tenacity.asyncio.AsyncRetrying"}
)
_WAIT_MODULES: Final = frozenset({"tenacity", "tenacity.wait"})
_WALL_CLOCK_SLEEPS: Final = frozenset(
    {"asyncio.sleep", "anyio.sleep", "trio.sleep", "time.sleep", "tenacity.nap.sleep"}
)
_MESSAGE: Final = (
    "this tenacity policy waits between attempts on the wall clock without a sleep= seam; pass an injected sleep "
    "so tests exercise retries without real delays"
)


@final
class RequireInjectableRetrySleep(Rule):
    id = "require-injectable-retry-sleep"
    code = "SARJ486"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Pass an injectable sleep to a tenacity retry policy that waits between attempts.",
        rationale=(
            "A tenacity policy built with a backoff wait and no sleep argument sleeps on the wall clock. Every test "
            "that exercises a transient failure pays the backoff, and exhausting an exponential policy costs the "
            "sum of every interval. Replacing tenacity's sleep from a test is a monkeypatch that SARJ445 forbids."
        ),
        remediation=(
            "Build the policy in a factory or constructor that accepts a sleep callable and pass it as sleep=, or "
            "accept the wait strategy itself as a dependency. Tests then inject a no-op or recording sleeper, or "
            "wait_none()."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only calls to tenacity.retry, tenacity.Retrying, and tenacity.AsyncRetrying resolved through imports are inspected; bare @retry, positional arguments, and **kwargs expansion abstain.",
            "A wait is reported only when it is built inline from tenacity wait_* calls, optionally combined with +; wait_none() and wait_fixed(0) do not wait. A wait read from a name, attribute, or other call is treated as injected.",
            "Any sleep= argument other than a wall-clock sleep imported from asyncio, anyio, trio, time, or tenacity.nap counts as a seam; the rule does not prove that tests replace it.",
            "The backoff library has no sleep parameter, so its decorators are not inspected. Test modules, test directories, conftest.py, test-support paths, and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="retry-backoff-without-sleep",
                title="A module-level retry decorator backs off on the wall clock",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/retry.py",
                        "from tenacity import retry, stop_after_attempt, wait_exponential\n\n"
                        "client_retry = retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/retry.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="retry-backoff-with-injected-sleep",
                title="A retry factory passes an injected sleep",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/retry.py",
                        "from collections.abc import Awaitable, Callable\n\n"
                        "from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential\n\n\n"
                        "def client_retrying(sleep: Callable[[float], Awaitable[None]]) -> AsyncRetrying:\n"
                        "    return AsyncRetrying(sleep=sleep, stop=stop_after_attempt(4), "
                        "wait=wait_exponential(multiplier=2))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/retry.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if (
            "tenacity" not in context.source
            or is_test_path(path)
            or is_test_support_path(path)
            or context.generated
            or context.tree is None
        ):
            return []
        imports = context.imports
        findings = [
            Diagnostic(
                path=path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
                severity=Severity.WARNING,
            )
            for call in context.nodes(ast.Call)
            if imports.resolved_qualified_name(call.func) in _POLICIES
            and _waits_without_seam(call, imports)
            and not is_suppressed(context.source_lines, call.lineno, self.code)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _waits_without_seam(call: ast.Call, imports: ImportIndex) -> bool:
    if call.args or any(keyword.arg is None for keyword in call.keywords):
        return False
    arguments = {keyword.arg: keyword.value for keyword in call.keywords}
    wait = arguments.get("wait")
    if wait is None or _wait_strategy(wait, imports) is not True:
        return False
    sleep = arguments.get("sleep")
    return sleep is None or imports.resolved_qualified_name(sleep) in _WALL_CLOCK_SLEEPS


def _wait_strategy(node: ast.expr, imports: ImportIndex) -> bool | None:
    match node:
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            parts = (_wait_strategy(left, imports), _wait_strategy(right, imports))
            return None if None in parts else any(parts)
        case ast.Call(func=func, args=args, keywords=keywords):
            module, _, strategy = (imports.resolved_qualified_name(func) or "").rpartition(".")
            if module not in _WAIT_MODULES or not strategy.startswith("wait_"):
                return None
            match strategy, args, keywords:
                case "wait_none", [], []:
                    return False
                case "wait_fixed", [ast.Constant(value=0)], []:
                    return False
                case "wait_fixed", [], [ast.keyword(arg="wait", value=ast.Constant(value=0))]:
                    return False
                case _:
                    return True
        case _:
            return None
