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
from sarj_python_lint.rules._store_sql import query_owner
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_cursor_calls


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BAD = "from psycopg import AsyncConnection\nasync def load(connection: AsyncConnection):\n    async with connection.cursor() as cursor:\n        await cursor.execute('SELECT id FROM item')\n    async with connection.cursor() as cursor:\n        await cursor.execute('SELECT id FROM owner')\n"
_GOOD = "from psycopg import AsyncConnection\nasync def load(connection: AsyncConnection):\n    async with connection.cursor() as cursor:\n        await cursor.execute('SELECT id FROM item')\n        rows = await cursor.fetchall()\n        await cursor.execute('SELECT id FROM owner')\n        return rows, await cursor.fetchall()\n"


@final
class PreferSinglePsycopgCursor(Rule):
    id = "prefer-single-psycopg-cursor"
    code = "SARJ561"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Review repeated Psycopg cursor creation within one function.",
        rationale="Repeated cursor construction can obscure one function's query orchestration and duplicate setup that could share a cursor.",
        remediation="Review whether one cursor can own these operations. Consume each result before reuse, retain distinct row factories or independent pipeline results when required, and preserve connection and transaction boundaries.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks import-proven Psycopg cursor creation, including typed connection parameters and constructor-injected pools. Emits one review warning at the first repeated creation in each lexical function.",
            "Cursors in separate functions or directly mutually exclusive if/else branches do not establish repeated creation. Wider path feasibility, mutually exclusive match/exception cases and helper-created cursors are not inferred.",
            "Multiple cursors are valid for independent result sets, different row factories, different connections and pipelines. This advisory requires review rather than claiming a database defect or automatically merging resource scopes.",
            "Generated code and unknown cursor-like APIs are excluded. Tests remain checked when they directly create proven Psycopg cursors.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-scopes",
                title="Review repeated cursor scopes",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/store.py", _BAD),),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="consumed-results",
                title="Reuse a cursor after consuming the result",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/store.py", _GOOD),),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        by_function: dict[ast.FunctionDef | ast.AsyncFunctionDef, list[ast.Call]] = {}
        for call in psycopg_cursor_calls(context):
            if (owner := query_owner(call, context).method) is not None:
                by_function.setdefault(owner, []).append(call)
        findings: list[Diagnostic] = []
        for calls in by_function.values():
            previous: list[ast.Call] = []
            for call in sorted(calls, key=lambda node: (node.lineno, node.col_offset)):
                if any(not _exclusive(earlier, call, context) for earlier in previous):
                    if not context.suppressions.is_suppressed(call.lineno, self.code):
                        findings.append(
                            Diagnostic(
                                context.path,
                                call.lineno,
                                call.col_offset + 1,
                                self.code,
                                "This function opens multiple Psycopg cursors; review reuse after consuming results. Preserve distinct row factories, connections and independent pipeline results when required.",
                                severity=Severity.WARNING,
                            )
                        )
                    break
                previous.append(call)
        return findings


def _exclusive(left: ast.Call, right: ast.Call, context: PythonFileContext) -> bool:
    right_branches = _branches(right, context)
    return any(
        branch in right_branches and right_branches[branch] != side for branch, side in _branches(left, context).items()
    )


def _branches(node: ast.AST, context: PythonFileContext) -> dict[ast.If, bool]:
    branches: dict[ast.If, bool] = {}
    child = node
    parent = context.parents.get(child)
    while parent is not None and not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
        if isinstance(parent, ast.If):
            if child in parent.body:
                branches[parent] = True
            elif child in parent.orelse:
                branches[parent] = False
        child, parent = parent, context.parents.get(parent)
    return branches
