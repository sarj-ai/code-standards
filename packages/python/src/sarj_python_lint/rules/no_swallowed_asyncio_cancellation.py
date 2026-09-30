from __future__ import annotations

import ast
from itertools import pairwise
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_ASYNCIO = frozenset({"asyncio", "asyncio.exceptions"})
_SIMPLE_STATEMENTS = (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete, ast.Pass)
_MESSAGE = (
    "CancelledError handler completes normally; re-raise caller cancellation after cleanup, "
    "or guard intentional child cancellation with the current task's cancellation state."
)


@final
class NoSwallowedAsyncioCancellation(Rule):
    id = "no-swallowed-asyncio-cancellation"
    code = "SARJ458"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Preserve cancellation when an async operation is cancelled.",
        rationale=(
            "Returning or falling through after catching CancelledError can make cancelled work look successful "
            "and interfere with task groups and timeout shutdown. Child cancellation must be distinguished from "
            "cancellation of the caller."
        ),
        remediation=(
            "Re-raise after cleanup. If child cancellation is an expected result, first propagate cancellation "
            "when asyncio.current_task().cancelling() is nonzero. Use an exact suppression for a documented "
            "boundary that deliberately consumes cancellation."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only explicit, import-proven asyncio.CancelledError handlers in async functions are inspected; broad handlers, contextlib.suppress, tests, support fixtures, and generated files are excluded.",
            "Only straight-line handlers with a return or normal fallthrough are reported. Compound handlers, re-raising, and translated exceptions are excluded. Any attribute call named uncancel is conservatively excluded without proving its receiver, so unrelated methods can hide a finding.",
            "A single-name task created by asyncio.create_task, immediately cancelled before a try that only awaits it, is intentionally excluded as child cleanup; this does not prove concurrent caller cancellation cannot occur.",
            "Try statements with control-transferring or compound finalizers are excluded, including handlers nested beneath them. Runtime helper effects and interprocedural task ownership are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="cancelled-operation-returns-success",
                title="Cancellation becomes a successful return",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "worker.py",
                        "import asyncio\n\nasync def worker():\n    try:\n        await asyncio.sleep(10)\n    except asyncio.CancelledError:\n        return None\n",
                    ),
                ),
                focus_path=PurePosixPath("worker.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="cancelled-operation-reraises",
                title="Cleanup preserves cancellation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "worker.py",
                        "import asyncio\n\nasync def worker():\n    try:\n        await asyncio.sleep(10)\n    except asyncio.CancelledError:\n        raise\n",
                    ),
                ),
                focus_path=PurePosixPath("worker.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "CancelledError" not in context.source:
            return []
        if context.generated or is_test_path(context.path) or is_test_support_path(context.path):
            return []
        tree = context.tree
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for function in nodes(tree, ast.AsyncFunctionDef, index=context.node_index):
            diagnostics.extend(_function_diagnostics(function, context, self.code))
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _function_diagnostics(function: ast.AsyncFunctionDef, context: PythonFileContext, code: str) -> list[Diagnostic]:
    local = tuple(_local_nodes(function))
    children = _owned_tasks(local, context.imports)
    previous = _preceding_statements(local)
    diagnostics: list[Diagnostic] = []
    for node in local:
        if not isinstance(node, ast.Try) or _owned_child_cleanup(node, previous.get(id(node)), children):
            continue
        for handler in node.handlers:
            if not _catches_cancellation(handler.type, context.imports) or not _normal_exit(handler.body):
                continue
            if is_suppressed(context.source_lines, handler.lineno, code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=handler.lineno,
                    col=handler.col_offset + 1,
                    code=code,
                    message=_MESSAGE,
                    severity=Severity.WARNING,
                )
            )
    return diagnostics


def _local_nodes(function: ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(reversed(function.body))
    yield function
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        if isinstance(node, ast.Try | ast.TryStar) and any(
            not isinstance(statement, _SIMPLE_STATEMENTS) for statement in node.finalbody
        ):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _catches_cancellation(exception: ast.expr | None, imports: ImportIndex) -> bool:
    if isinstance(exception, ast.Tuple):
        return any(_catches_cancellation(item, imports) for item in exception.elts)
    return exception is not None and imports.resolves(exception, sources=_ASYNCIO, symbol="CancelledError")


def _normal_exit(statements: list[ast.stmt]) -> bool:
    for statement in statements:
        if any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "uncancel"
            for node in ast.walk(statement)
        ):
            return False
        if isinstance(statement, ast.Return):
            return True
        if not isinstance(statement, _SIMPLE_STATEMENTS):
            return False
    return True


def _owned_tasks(local: tuple[ast.AST, ...], imports: ImportIndex) -> frozenset[str]:
    bindings: dict[str, list[ast.AST]] = {}
    for node in local:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            bindings.setdefault(node.id, []).append(node)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
        ):
            bindings.setdefault(node.value.id, []).append(node)
    return frozenset(
        node.targets[0].id
        for node in local
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and len(bindings[node.targets[0].id]) == 1
        and isinstance(node.value, ast.Call)
        and imports.resolves(node.value.func, sources=frozenset({"asyncio"}), symbol="create_task")
    )


def _preceding_statements(local: tuple[ast.AST, ...]) -> dict[int, ast.stmt]:
    previous: dict[int, ast.stmt] = {}
    for node in local:
        for suite in _statement_suites(node):
            for first, second in pairwise(suite):
                previous[id(second)] = first
    return previous


def _owned_child_cleanup(node: ast.Try, previous: ast.stmt | None, children: frozenset[str]) -> bool:
    if len(node.body) != 1:
        return False
    match node.body[0], previous:
        case (
            ast.Expr(value=ast.Await(value=ast.Name(id=awaited))),
            ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id=cancelled), attr="cancel"))),
        ):
            return awaited == cancelled and awaited in children
        case _:
            return False


def _statement_suites(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    match node:
        case ast.Try() | ast.TryStar():
            return node.body, node.orelse, node.finalbody
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.AsyncFunctionDef() | ast.With() | ast.AsyncWith() | ast.ExceptHandler() | ast.match_case():
            return (node.body,)
        case _:
            return ()
