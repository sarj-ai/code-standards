from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.keyword):
            if node.arg != _ROW_FACTORY_KW:
                continue
            if not _is_proven_dict_row(node.value, bindings):
                continue
            owner = _enclosing_function(node, parents)
            if owner is not None and (_fetch_call_count(owner) > 1 or _has_single_column_select(owner)):
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


def _enclosing_function(
    node: ast.AST,
    parents: dict[int, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(id(current))
    return None


def _fetch_call_count(owner: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return sum(
        1
        for node in ast.walk(owner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fetchall", "fetchmany", "fetchone"}
    )


_SELECT_PROJECTION_RE = re.compile(r"\bselect\b(?P<projection>.*?)\bfrom\b", re.IGNORECASE | re.DOTALL)
_RETURNING_PROJECTION_RE = re.compile(r"\breturning\b(?P<projection>.*?)(?:;|$)", re.IGNORECASE | re.DOTALL)


def _has_single_column_select(owner: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(owner):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for pattern in (_SELECT_PROJECTION_RE, _RETURNING_PROJECTION_RE):
            match = pattern.search(node.value)
            if match is not None and not _has_top_level_comma(match.group("projection")):
                return True
    return False


def _has_top_level_comma(projection: str) -> bool:
    depth = 0
    quote: str | None = None
    for char in projection:
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            return True
    return False
