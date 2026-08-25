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


_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_CLAUSE_BOUNDARY = re.compile(
    r"\b(?:LIMIT|OFFSET|FETCH|FOR|UNION|INTERSECT|EXCEPT|RETURNING|WINDOW|QUALIFY|"
    r"GROUP\s+BY|HAVING|ORDER\s+BY)\b",
    re.IGNORECASE,
)
_TIMESTAMP_ITEM = re.compile(
    r"(?:(?:[A-Za-z_][A-Za-z0-9_$]*\s*\.\s*)*)(?P<column>[A-Za-z_][A-Za-z0-9_$]*_at)"
    r"(?:\s+(?:ASC|DESC))?(?:\s+NULLS\s+(?:FIRST|LAST))?\s*\Z",
    re.IGNORECASE,
)


@final
class TimestampOrderRequiresTiebreaker(Rule):
    id = "timestamp-order-requires-tiebreaker"
    code = "SARJ407"
    documentation = RuleDocumentation(
        summary="Store query ending its order with a `*_at` timestamp must add a stable tie-break key.",
        rationale=(
            "Timestamps are not unique, so rows with the same timestamp value have no stable relative order. "
            "That can make pagination and repeated reads skip, repeat, or reorder rows."
        ),
        remediation="Add a stable key after the timestamp, such as `ORDER BY created_at DESC, id DESC`.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        aliases=("created-at-order-requires-tiebreaker",),
        limitations=(
            "Only fully reconstructable SQL string literals in recognized production store modules are analyzed.",
            (
                "The rule reports an exact, optionally qualified unquoted `*_at` column only when it is the final "
                "same-depth `ORDER BY` item; any later same-depth ordering item is accepted as an explicit tie-break."
            ),
            (
                "Dynamic string construction, formatted strings, quoted identifiers, expressions containing "
                "a timestamp column, and non-SELECT fragments are excluded."
            ),
            "The intended stable key cannot be inferred safely, so the rule does not offer an autofix.",
        ),
        examples=(
            RuleExample(
                example_id="created-at-is-the-only-order-key",
                title="A store query orders only by a timestamp",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'QUERY = "SELECT id, created_at FROM task ORDER BY created_at DESC LIMIT 50"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="created-at-is-followed-by-id",
                title="A stable key breaks equal-timestamp ties",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'QUERY = "SELECT id, created_at FROM task ORDER BY created_at DESC, id DESC LIMIT 50"\n',
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
        if not is_store_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diagnostics: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed:
                continue
            if isinstance(node, (ast.BinOp, ast.JoinedStr)):
                consumed.update(id(child) for child in walk(node))
            if not _is_fully_static_string(node):
                continue
            text = sql_string_value(node)
            if text is None:
                continue
            sql = strip_sql_noise(text)
            if _QUERY_SHAPE.search(sql) is None or (timestamp := _timestamp_ending_order_clause(sql)) is None:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.ERROR,
                    message=(
                        f"Store query leaves `{timestamp}` as its final ordering item; add a stable tie-break key "
                        "after it, such as `id` (for example, `ORDER BY created_at DESC, id DESC`)."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics


def _is_fully_static_string(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Add)
        and _is_fully_static_string(node.left)
        and _is_fully_static_string(node.right)
    )


def _timestamp_ending_order_clause(sql: str) -> str | None:
    depths = _depths(sql)
    for order in _ORDER_BY.finditer(sql):
        clause_depth = depths[order.start()]
        item_start = order.end()
        clause_end = len(sql)
        index = item_start
        while index < len(sql):
            if (
                depths[index] < clause_depth
                or sql[index] == ";"
                or (sql[index] == ")" and depths[index] == clause_depth)
            ):
                clause_end = index
                break
            if depths[index] == clause_depth:
                if sql[index] == ",":
                    item_start = index + 1
                elif _CLAUSE_BOUNDARY.match(sql, index) is not None:
                    clause_end = index
                    break
            index += 1
        if (timestamp := _TIMESTAMP_ITEM.fullmatch(sql[item_start:clause_end].strip())) is not None:
            return timestamp.group("column")
    return None


def _depths(sql: str) -> list[int]:
    depths: list[int] = []
    depth = 0
    for character in sql:
        depths.append(depth)
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
    return depths
