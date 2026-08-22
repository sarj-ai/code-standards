from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FETCH_METHODS = frozenset({"fetchall", "fetchmany", "fetchone"})


class _BoundCursor(NamedTuple):
    call: ast.Call
    variable: str


@final
class RequireValidatedRowFactory(Rule):
    id = "require-validated-row-factory"
    code = "SARJ414"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Fetched Psycopg rows must be parsed by `class_row(Model)`.",
        rationale="Bare and tuple-like cursors let unvalidated positional rows cross the database boundary.",
        remediation="Pass `row_factory=class_row(Model)`; define a small row model for a projection.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only cursors bound by a with statement and fetched in the same function are inspected.",
            "Test files are excluded, and `dict_row` remains exclusively owned by SARJ013.",
            "Dynamic/ad-hoc result shapes require an exact local suppression.",
        ),
        examples=(
            RuleExample(
                example_id="bare-fetched-cursor",
                title="A fetched cursor returns positional rows",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "store.py", "def load(conn):\n    with conn.cursor() as cur:\n        return cur.fetchone()\n"
                    ),
                ),
                focus_path=PurePosixPath("store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validated-fetched-cursor",
                title="A fetched cursor validates a row model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "store.py",
                        "def load(conn):\n    with conn.cursor(row_factory=class_row(PendingTimeRow)) as cur:\n        return cur.fetchone()\n",
                    ),
                ),
                focus_path=PurePosixPath("store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or is_test_path(path) or "migrations" in {part.lower() for part in path.parts}:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            fetched = _fetched_names(function)
            for cursor_call, name in _bound_cursors(function):
                if name not in fetched or _uses_class_row(cursor_call) or _uses_dict_row(cursor_call):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=cursor_call.lineno,
                        col=cursor_call.col_offset + 1,
                        code=self.code,
                        severity=Severity.ERROR,
                        message=(
                            "fetched Psycopg cursor has no `class_row(Model)` factory; validate the result at the DB "
                            "boundary (use a one-field model for scalar projections)"
                        ),
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _bound_cursors(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_BoundCursor]:
    result: list[_BoundCursor] = []
    for node in ast.walk(function):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            expression = item.context_expr
            if (
                isinstance(expression, ast.Call)
                and isinstance(expression.func, ast.Attribute)
                and expression.func.attr == "cursor"
                and isinstance(item.optional_vars, ast.Name)
            ):
                result.append(_BoundCursor(expression, item.optional_vars.id))
    return result


def _fetched_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    return frozenset(
        call.func.value.id
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in _FETCH_METHODS
        and isinstance(call.func.value, ast.Name)
    )


def _uses_class_row(call: ast.Call) -> bool:
    for keyword in call.keywords:
        value = keyword.value
        if keyword.arg != "row_factory" or not isinstance(value, ast.Call):
            continue
        func = value.func
        if (isinstance(func, ast.Name) and func.id == "class_row") or (
            isinstance(func, ast.Attribute) and func.attr == "class_row"
        ):
            return bool(value.args)
    return False


def _uses_dict_row(call: ast.Call) -> bool:
    return any(
        keyword.arg == "row_factory"
        and (
            (isinstance(keyword.value, ast.Name) and keyword.value.id == "dict_row")
            or (isinstance(keyword.value, ast.Attribute) and keyword.value.attr == "dict_row")
        )
        for keyword in call.keywords
    )
