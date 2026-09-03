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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_DYNAMIC_VALUE = r"(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|:__sarj_dynamic__)"
_OFFSET_PAGINATION = re.compile(
    rf"\bOFFSET\s+{_DYNAMIC_VALUE}",
    re.IGNORECASE,
)
_MYSQL_OFFSET_PAGINATION = re.compile(rf"\bLIMIT\s+{_DYNAMIC_VALUE}\s*,", re.IGNORECASE)
_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_MIGRATION_PARTS = frozenset({"migration", "migrations"})
_QUOTED_IDENTIFIER = re.compile(r"`[^`\n]*`|\[[^\]\n]*\]")
_MYSQL_COMMENT = re.compile(r"(?m)#[^\n]*$")


@final
class NoOffsetPagination(Rule):
    id: str = "no-offset-pagination"
    code: str = "SARJ025"
    documentation = RuleDocumentation(
        summary="Potentially unbounded `OFFSET` pagination in store SQL.",
        rationale=(
            "Dynamic offsets may require scanning discarded rows and may skip or repeat results during concurrent writes."
        ),
        remediation=(
            "Use a stable, immutable, unique ordering and a cursor predicate with the same direction; include a unique "
            "tie-breaker for non-unique sort columns. Keep OFFSET with a reasoned suppression for demonstrably bounded "
            "or static data, or an intentional random-access page contract."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only SQL string literals in recognized store modules are analyzed.",
            "Only dynamic OFFSET values in credible SELECT queries are reported; fixed ordinal offsets are excluded.",
            "Generated files, migrations, docstrings, comments, quoted identifiers, and BigQuery `WITH OFFSET AS` array indexing are excluded.",
            "ORM pagination APIs are outside this embedded-SQL rule.",
        ),
        examples=(
            RuleExample(
                example_id="offset-page-query",
                title="Page selected with an offset",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'QUERY = "SELECT id FROM task ORDER BY id LIMIT :limit OFFSET :offset"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="keyset-page-query",
                title="Page selected with a stable composite cursor",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'QUERY = "SELECT id FROM task WHERE (created_at, id) < (:cursor_created_at, :cursor_id) ORDER BY created_at DESC, id DESC LIMIT :limit"\n',
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
        if (
            not is_store_module(path)
            or is_generated(path, source)
            or _MIGRATION_PARTS.intersection(part.casefold() for part in path.parts)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        consumed: set[int] = set()
        docstrings = _docstring_node_ids(tree)
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed or id(node) in docstrings:
                continue
            text = _sql_value(node)
            if text is None:
                continue
            consumed.update(id(sub) for sub in walk(node))

            sql = _mask_dialect_noise(strip_sql_noise(text))
            if _QUERY_SHAPE.search(sql) is None or (
                _OFFSET_PAGINATION.search(sql) is None and _MYSQL_OFFSET_PAGINATION.search(sql) is None
            ):
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        "Dynamic OFFSET pagination may scan skipped rows and drift under writes; use a stable unique "
                        "keyset cursor, or document why bounded/random page access requires OFFSET."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _sql_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                pieces.append(":__sarj_dynamic__")
        return "".join(pieces)
    return sql_string_value(node)


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    result: set[int] = set()
    for owner in nodes(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef):
        if not owner.body or not isinstance(owner.body[0], ast.Expr):
            continue
        value = owner.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            result.add(id(value))
    return result


def _mask_dialect_noise(sql: str) -> str:
    sql = _QUOTED_IDENTIFIER.sub(lambda match: " " * len(match.group(0)), sql)
    return _MYSQL_COMMENT.sub(lambda match: " " * len(match.group(0)), sql)
