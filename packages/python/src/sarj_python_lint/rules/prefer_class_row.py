"""SARJ013 — Psycopg `row_factory=dict_row` where a validated model row is intended.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_class_row.py
"""

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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from pathlib import Path


_ROW_FACTORY_KW = "row_factory"
_BANNED_FACTORY = "dict_row"
_PSYCOPG = "psycopg"
_ROWS = "rows"


@final
class PreferClassRow(Rule):
    id: str = "prefer-class-row"
    code: str = "SARJ013"
    documentation = RuleDocumentation(
        summary="Use a validated model row instead of Psycopg `dict_row`.",
        rationale="Dictionary rows cross the database boundary without validating field names or values against a model.",
        remediation="Pass `class_row(Model)` as the row factory for queries that return a stable model shape.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule matches any `row_factory` keyword whose value ends in `dict_row`.",
            "Ad hoc or dynamically selected row shapes require a local suppression when a class row is unsuitable.",
        ),
        examples=(
            RuleExample(
                example_id="dictionary-row-factory",
                title="Cursor returns unvalidated dictionaries",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "from psycopg.rows import dict_row\n\ncursor = connection.cursor(row_factory=dict_row)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validated-class-row-factory",
                title="Cursor validates rows into a model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "from psycopg.rows import class_row\n\ncursor = connection.cursor(row_factory=class_row(Task))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        bindings = _psycopg_bindings(tree)
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.keyword):
            if node.arg != _ROW_FACTORY_KW:
                continue
            if not _is_proven_dict_row(node.value, bindings):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.value.lineno,
                    col=node.value.col_offset + 1,
                    code=self.code,
                    message=(
                        "`row_factory=dict_row` yields unvalidated dict rows — "
                        "prefer `class_row(YourModel)` to validate at the DB boundary "
                        "(suppress with `# sarj-noqa: SARJ013` for genuine ad-hoc shapes)"
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _PsycopgBindings:
    def __init__(self) -> None:
        self.direct: set[str] = set()
        self.row_modules: set[str] = set()
        self.psycopg_modules: set[str] = set()
        self.rebound: set[str] = set()


def _psycopg_bindings(tree: ast.Module) -> _PsycopgBindings:
    """Resolve only dict-row bindings whose psycopg provenance is visible."""
    result = _PsycopgBindings()
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        if isinstance(node, ast.ImportFrom):
            if node.module == "psycopg.rows":
                result.direct.update(
                    alias.asname or alias.name for alias in node.names if alias.name == _BANNED_FACTORY
                )
            elif node.module == _PSYCOPG:
                result.row_modules.update(alias.asname or alias.name for alias in node.names if alias.name == _ROWS)
        else:
            for alias in node.names:
                if alias.name == _PSYCOPG:
                    result.psycopg_modules.add(alias.asname or _PSYCOPG)
                elif alias.name == "psycopg.rows":
                    if alias.asname:
                        result.row_modules.add(alias.asname)
                    else:
                        result.psycopg_modules.add(_PSYCOPG)

    proven_roots = result.direct | result.row_modules | result.psycopg_modules
    if not proven_roots:
        return result
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in proven_roots:
            result.rebound.add(node.id)
        elif isinstance(node, ast.arg) and node.arg in proven_roots:
            result.rebound.add(node.arg)
        elif (
            isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar),
            )
            and node.name in proven_roots
        ):
            result.rebound.add(node.name)
    return result


def _is_proven_dict_row(node: ast.expr, bindings: _PsycopgBindings) -> bool:
    """Report whether `node` resolves to `psycopg.rows.dict_row`."""
    if isinstance(node, ast.NamedExpr):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id in bindings.direct and node.id not in bindings.rebound
    if not (isinstance(node, ast.Attribute) and node.attr == _BANNED_FACTORY):
        return False
    receiver = node.value
    if isinstance(receiver, ast.Name):
        return receiver.id in bindings.row_modules and receiver.id not in bindings.rebound
    return (
        isinstance(receiver, ast.Attribute)
        and receiver.attr == _ROWS
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id in bindings.psycopg_modules
        and receiver.value.id not in bindings.rebound
    )
