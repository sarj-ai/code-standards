from __future__ import annotations

import ast
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
    Severity,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex

_ASYNCIO = frozenset({"asyncio"})
_FAILURE_TYPES = frozenset({"BaseException", "Exception"})
_MINIMUM_UNPACKED_CHECKS = 2
_MESSAGE = (
    "Only the first exception gathered with return_exceptions=True is raised and the rest are discarded; use "
    "asyncio.TaskGroup when the first failure should cancel the siblings, or raise an ExceptionGroup of every "
    "failure when all operations must finish."
)

_LOOP = """\
import asyncio


async def delete_all(paths: list[str]) -> None:
    results = await asyncio.gather(*(delete(path) for path in paths), return_exceptions=True)
{handling}
"""


@final
class NoGatherFirstExceptionReraise(Rule):
    id = "no-gather-first-exception-reraise"
    code = "SARJ598"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Raise every gathered failure instead of only the first.",
        rationale=(
            "asyncio.gather(..., return_exceptions=True) waits for every operation and returns their failures as "
            "values. Scanning the results and raising the first exception discards every later failure, so "
            "concurrent cleanup or fan-out can lose the errors that explain what is still broken."
        ),
        remediation=(
            "Use asyncio.TaskGroup when the first failure should cancel the siblings. When every operation must "
            "finish, as in cleanup, collect all failures and raise BaseExceptionGroup or ExceptionGroup so none is "
            "lost."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Only an import-proven asyncio.gather awaited directly into a local name or a tuple of names with a "
                "literal return_exceptions=True is tracked. Later statements in the same block are inspected; "
                "results passed through helpers, rebound or stored elsewhere are not followed."
            ),
            (
                "A loop over the results (directly, through zip or enumerate) is reported when an "
                "isinstance(item, BaseException | Exception) branch raises that item. Unpacked results are reported "
                "when at least two names are checked and raised in turn. One diagnostic is reported per gather, at "
                "its first such raise. Raising a collected list element or an "
                "exception group, keeping successes, and handling specific exception types are not reported."
            ),
            "Tests, test support and generated files are excluded. No automatic rewrite is offered.",
        ),
        examples=(
            RuleExample(
                example_id="first-cleanup-failure",
                title="Only the first cleanup failure is raised",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "storage/cleanup.py",
                        _LOOP.format(
                            handling=(
                                "    for result in results:\n"
                                "        if isinstance(result, BaseException):\n"
                                "            raise result"
                            )
                        ),
                    ),
                ),
                focus_path=PurePosixPath("storage/cleanup.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="every-cleanup-failure",
                title="Every cleanup failure is raised together",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "storage/cleanup.py",
                        _LOOP.format(
                            handling=(
                                "    failures = [result for result in results if isinstance(result, Exception)]\n"
                                "    if failures:\n"
                                '        raise ExceptionGroup("cleanup failed", failures)'
                            )
                        ),
                    ),
                ),
                focus_path=PurePosixPath("storage/cleanup.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "return_exceptions" not in context.symbol_source:
            return []
        if context.generated or is_test_path(context.path) or is_test_support_path(context.path):
            return []
        tree = context.tree
        if tree is None:
            return []
        imports = context.imports
        diagnostics: list[Diagnostic] = []
        for suite in _suites(tree):
            for index, statement in enumerate(suite):
                targets = _gathered_targets(statement, imports)
                if targets is None:
                    continue
                raised = next(
                    (
                        candidate
                        for candidate in _first_failure_raises(targets, suite[index + 1 :], imports)
                        if not context.suppressions.is_suppressed(candidate.lineno, self.code)
                    ),
                    None,
                )
                if raised is not None:
                    diagnostics.append(
                        Diagnostic(
                            path=context.path,
                            line=raised.lineno,
                            col=raised.col_offset + 1,
                            code=self.code,
                            message=_MESSAGE,
                            severity=Severity.WARNING,
                        )
                    )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _suites(tree: ast.Module) -> Iterator[list[ast.stmt]]:
    for node in ast.walk(tree):
        match node:
            case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
                yield node.body
                yield node.orelse
            case ast.Try() | ast.TryStar():
                yield node.body
                yield node.orelse
                yield node.finalbody
            case (
                ast.Module()
                | ast.FunctionDef()
                | ast.AsyncFunctionDef()
                | ast.ClassDef()
                | ast.With()
                | ast.AsyncWith()
                | ast.ExceptHandler()
                | ast.match_case()
            ):
                yield node.body
            case _:
                pass


def _gathered_targets(statement: ast.stmt, imports: ImportIndex) -> ast.expr | None:
    match statement:
        case ast.Assign(targets=[target], value=ast.Await(value=ast.Call() as call)):
            pass
        case ast.AnnAssign(target=target, value=ast.Await(value=ast.Call() as call)):
            pass
        case _:
            return None
    if not imports.resolves(call.func, sources=_ASYNCIO, symbol="gather"):
        return None
    if not any(
        keyword.arg == "return_exceptions" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    ):
        return None
    match target:
        case ast.Name():
            return target
        case ast.Tuple(elts=elements) if all(isinstance(element, ast.Name) for element in elements):
            return target
        case _:
            return None


def _first_failure_raises(target: ast.expr, following: list[ast.stmt], imports: ImportIndex) -> list[ast.Raise]:
    match target:
        case ast.Name(id=results):
            return [
                raised
                for statement in following
                if isinstance(statement, ast.For | ast.AsyncFor) and _iterates(statement.iter, results, imports)
                for raised in _guarded_raises(statement.body, _target_names(statement.target), imports)
            ]
        case _:
            names = frozenset(element.id for element in ast.walk(target) if isinstance(element, ast.Name))
            raises = _guarded_raises(following, names, imports)
            return raises if len(raises) >= _MINIMUM_UNPACKED_CHECKS else []


def _iterates(iterable: ast.expr, results: str, imports: ImportIndex) -> bool:
    match iterable:
        case ast.Name(id=name):
            return name == results
        case ast.Call(func=ast.Name(id="zip" | "enumerate" as helper), args=arguments) if imports.builtin_is_unshadowed(
            helper
        ):
            return any(isinstance(argument, ast.Name) and argument.id == results for argument in arguments)
        case _:
            return False


def _target_names(target: ast.expr) -> frozenset[str]:
    return frozenset(node.id for node in ast.walk(target) if isinstance(node, ast.Name))


def _guarded_raises(statements: list[ast.stmt], names: frozenset[str], imports: ImportIndex) -> list[ast.Raise]:
    raises: list[ast.Raise] = []
    for statement in statements:
        if not isinstance(statement, ast.If):
            continue
        checked = _failure_check(statement.test, imports)
        if checked is None or checked not in names:
            continue
        raises.extend(
            child
            for child in statement.body
            if isinstance(child, ast.Raise) and isinstance(child.exc, ast.Name) and child.exc.id == checked
        )
    return raises


def _failure_check(test: ast.expr, imports: ImportIndex) -> str | None:
    match test:
        case ast.Call(func=ast.Name(id="isinstance"), args=[ast.Name(id=checked), classes], keywords=[]):
            pass
        case _:
            return None
    if not imports.builtin_is_unshadowed("isinstance"):
        return None
    if any(
        isinstance(candidate, ast.Name)
        and candidate.id in _FAILURE_TYPES
        and imports.builtin_is_unshadowed(candidate.id)
        for candidate in _alternatives(classes)
    ):
        return checked
    return None


def _alternatives(classes: ast.expr) -> Iterator[ast.expr]:
    match classes:
        case ast.Tuple(elts=elements):
            for element in elements:
                yield from _alternatives(element)
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            yield from _alternatives(left)
            yield from _alternatives(right)
        case _:
            yield classes
