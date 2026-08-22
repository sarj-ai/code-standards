from __future__ import annotations

import ast
from dataclasses import dataclass
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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import is_store_module


if TYPE_CHECKING:
    from pathlib import Path


@final
class PreferOneForRequiredRow(Rule):
    id = "prefer-one-for-required-row"
    code = "SARJ422"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Use a required-row helper instead of asserting that `fetchone()` returned a row.",
        rationale=(
            "A bare assertion is removed by optimized Python and repeats the database contract at each call site; "
            "a shared helper preserves the invariant and raises one intentional domain error."
        ),
        remediation=(
            "Wrap the fetch in the repository's required-row helper, for example "
            "`row = one(await cursor.fetchone())`, and remove the non-None assertion."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only an immediate exact `row is not None` assertion after `fetchone()` in production store modules is inspected.",
            "The rule does not infer that an optional lookup must return a row and does not choose an import path for the helper.",
        ),
        examples=(
            RuleExample(
                example_id="required-returning-row",
                title="Use the shared required-row contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings_store.py",
                        "async def save(cursor):\n"
                        "    row = await cursor.fetchone()\n"
                        "    assert row is not None, 'RETURNING must yield a row'\n"
                        "    return row\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="required-row-helper",
                title="Centralize the missing-row failure",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings_store.py",
                        "async def save(cursor):\n    return one(await cursor.fetchone())\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for owner in ast.walk(tree):
            for statements in _statement_blocks(owner):
                for assignment, assertion in pairwise(statements):
                    binding = _fetchone_binding(assignment)
                    if binding is None or not _asserts_not_none(assertion, binding.name):
                        continue
                    diagnostics.append(
                        Diagnostic(
                            path=path,
                            line=assignment.lineno,
                            col=assignment.col_offset + 1,
                            code=self.code,
                            message=(
                                f"`{binding.name}` is asserted non-None immediately after `fetchone()`. Use the shared "
                                f"required-row helper (for example `{binding.name} = one({binding.expression})`) so "
                                "optimized Python cannot remove the contract."
                            ),
                            severity=Severity.ERROR,
                        )
                    )
        return diagnostics


def _statement_blocks(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    match node:
        case ast.Module() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return (node.body,)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.With() | ast.AsyncWith() | ast.ExceptHandler() | ast.match_case():
            return (node.body,)
        case ast.Try() | ast.TryStar():
            return node.body, node.orelse, node.finalbody, *(handler.body for handler in node.handlers)
        case _:
            return ()


@dataclass(frozen=True, slots=True)
class _FetchBinding:
    name: str
    expression: str


def _fetchone_binding(statement: ast.stmt) -> _FetchBinding | None:
    target: ast.expr
    value: ast.expr | None
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        value = statement.value
    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
        target = statement.target
        value = statement.value
    else:
        return None
    if not isinstance(target, ast.Name):
        return None
    call = value.value if isinstance(value, ast.Await) else value
    if not isinstance(call, ast.Call) or call.args or call.keywords:
        return None
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "fetchone":
        return None
    return _FetchBinding(target.id, ast.unparse(value))


def _asserts_not_none(statement: ast.stmt, binding: str) -> bool:
    if not isinstance(statement, ast.Assert) or not isinstance(statement.test, ast.Compare):
        return False
    comparison = statement.test
    if len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.IsNot) or len(comparison.comparators) != 1:
        return False
    left, right = comparison.left, comparison.comparators[0]
    return (_is_name(left, binding) and _is_none(right)) or (_is_none(left) and _is_name(right, binding))


def _is_name(node: ast.expr, expected: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


__all__ = ["PreferOneForRequiredRow"]
