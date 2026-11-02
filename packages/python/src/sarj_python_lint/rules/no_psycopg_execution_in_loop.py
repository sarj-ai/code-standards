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
    is_suppressed,
)
from sarj_python_lint.rules._store_writes import known_single_iteration
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_execution_calls


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BAD = "from psycopg import AsyncConnection\nasync def remove(connection: AsyncConnection, rows):\n    for row in rows:\n        await connection.execute('DELETE FROM item WHERE id = %s', (row.id,))\n"
_GOOD = "from psycopg import AsyncConnection\nasync def remove(connection: AsyncConnection, rows):\n    identifiers = [row.id for row in rows]\n    await connection.execute('DELETE FROM item WHERE id = ANY(%s)', (identifiers,))\n"


@final
class NoPsycopgExecutionInLoop(Rule):
    id = "no-psycopg-execution-in-loop"
    code = "SARJ560"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use bounded bulk queries instead of executing Psycopg operations inside item loops.",
        rationale="Executing a database operation for each input item makes round trips scale with collection size, including loops that prepare each row before executing.",
        remediation="Collect inputs and use a bounded set-based query, typed bulk store operation or executemany batch. Preserve tenant checks, revision predicates, transaction boundaries, returned rows, ordering and deliberate sequential effects.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks import-proven Psycopg execute calls in for/async-for bodies and repeated comprehension expressions, including injected pools, connections and cursors. Explicit executemany batch loops remain valid for bounded chunking.",
            "In-memory preparation, one-shot iteration inputs, known zero/single-item loops, deferred nested functions, unrelated execute methods and generated code are excluded. While retry/stream loops and interprocedural helper execution are not inferred.",
            "SARJ518 owns its narrower invariant-write cases, so one location receives only that specific executemany diagnostic. Unknown SQL and result-consuming loops still require bulk-query review; no automatic rewrite changes database semantics.",
        ),
        examples=(
            RuleExample(
                example_id="per-item-write",
                title="A connection executes once per item",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/store.py", _BAD),),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="set-based-write",
                title="One query consumes the collected identifiers",
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
        calls = [
            call
            for call in psycopg_execution_calls(context, include_injected=True, include_probes=False)
            if isinstance(call.func, ast.Attribute) and call.func.attr == "execute" and _repeated(call, context)
        ]
        if not calls:
            return []
        unique = {(call.lineno, call.col_offset): call for call in calls}
        return [
            Diagnostic(
                context.path,
                call.lineno,
                call.col_offset + 1,
                self.code,
                "This item loop executes a Psycopg operation per iteration; collect inputs and prefer a bounded bulk query or bulk store method, preserving transaction, result and failure semantics.",
                severity=Severity.WARNING,
            )
            for call in unique.values()
            if not is_suppressed(context.source_lines, call.lineno, self.code)
        ]


def _repeated(call: ast.Call, context: PythonFileContext) -> bool:
    child: ast.AST = call
    parent = context.parents.get(child)
    while parent is not None:
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            return False
        if (
            isinstance(parent, ast.For | ast.AsyncFor)
            and child in parent.body
            and not known_single_iteration(parent.iter)
        ):
            return True
        if isinstance(parent, ast.comprehension):
            owner = context.parents.get(parent)
            if child in parent.ifs or (
                child is parent.iter
                and isinstance(owner, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp)
                and owner.generators.index(parent) > 0
            ):
                return True
        if isinstance(parent, ast.ListComp | ast.SetComp | ast.GeneratorExp) and child is parent.elt:
            return True
        if isinstance(parent, ast.DictComp) and child in {parent.key, parent.value}:
            return True
        child, parent = parent, context.parents.get(parent)
    return False
