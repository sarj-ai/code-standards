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
_GROUPED_OR_DISTINCT = re.compile(r"\b(?:GROUP\s+BY|SELECT\s+DISTINCT)\b", re.IGNORECASE)
_WITH_TIES = re.compile(r"^\s*FETCH\b[\s\S]*?\bWITH\s+TIES\b", re.IGNORECASE)
_UNSTABLE_ITEM = re.compile(
    r"(?:random|rand|newid|uuid|now|clock_timestamp)\s*\([^)]*\)|[-+]?\d+(?:\.\d+)?|null",
    re.IGNORECASE,
)
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
        summary=(
            "Bounded store SQL whose final result-order key looks like a `*_at` timestamp should include a "
            "deterministic secondary key."
        ),
        rationale=(
            "Timestamp columns are not necessarily unique, so bounded reads can choose different rows at a page or "
            "top-N boundary. Keyset pagination also needs the same secondary key in its cursor predicate."
        ),
        remediation=(
            "Add a deterministic unique key after the timestamp. For keyset pagination, include the key in both the "
            "ORDER BY tuple and cursor predicate, such as `(created_at, id) < (%s, %s)`."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        aliases=("created-at-order-requires-tiebreaker",),
        limitations=(
            "Only fully reconstructable SQL string literals in recognized production store modules are analyzed.",
            (
                "The rule reports an exact, optionally qualified unquoted `*_at` column only when it is the final "
                "same-depth `ORDER BY` item before LIMIT, OFFSET, or FETCH, or when only a volatile/constant pseudo-key "
                "follows. Uniqueness is not schema-proven."
            ),
            (
                "Dynamic string construction, formatted strings, quoted identifiers, expressions containing "
                "a timestamp column, and non-SELECT fragments are excluded."
            ),
            "The intended stable key cannot be inferred safely, so the rule does not offer an autofix.",
            "Grouped, DISTINCT, WITH TIES, unbounded, window-only, aggregate-only, and docstring SQL are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="created-at-is-the-only-order-key",
                title="A store query orders only by a timestamp",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "QUERY = (\n"
                        '    "SELECT id, created_at FROM task "\n'
                        '    "WHERE created_at < %s "\n'
                        '    "ORDER BY created_at DESC LIMIT 50"\n'
                        ")\n",
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
                        "QUERY = (\n"
                        '    "SELECT id, created_at FROM task "\n'
                        '    "WHERE (created_at, id) < (%s, %s) "\n'
                        '    "ORDER BY created_at DESC, id DESC LIMIT 50"\n'
                        ")\n",
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
        docstrings = _docstring_nodes(tree)
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed or id(node) in docstrings:
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
                    severity=Severity.WARNING,
                    message=(
                        f"Bounded query leaves `{timestamp}` as its final deterministic ordering item; add a unique "
                        "secondary key. For keyset pagination, include it in both ORDER BY and the cursor predicate."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics


def _is_fully_static_string(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return all(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in node.values)
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Add)
        and _is_fully_static_string(node.left)
        and _is_fully_static_string(node.right)
    )


def _timestamp_ending_order_clause(sql: str) -> str | None:
    if _GROUPED_OR_DISTINCT.search(sql) is not None:
        return None
    depths = _depths(sql)
    for order in _ORDER_BY.finditer(sql):
        clause_depth = depths[order.start()]
        item_start = order.end()
        clause_end = len(sql)
        boundary = ""
        item_starts = [item_start]
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
                    item_starts.append(index + 1)
                elif (boundary_match := _CLAUSE_BOUNDARY.match(sql, index)) is not None:
                    clause_end = index
                    boundary = boundary_match.group(0).upper()
                    break
            index += 1
        if boundary not in {"LIMIT", "OFFSET", "FETCH"} or (
            boundary == "FETCH" and _WITH_TIES.match(sql[clause_end:]) is not None
        ):
            continue
        item_ends = [start - 1 for start in item_starts[1:]] + [clause_end]
        items = [sql[start:end].strip() for start, end in zip(item_starts, item_ends, strict=True)]
        for item_index, item in enumerate(items):
            timestamp = _TIMESTAMP_ITEM.fullmatch(item)
            if timestamp is not None and (
                item_index == len(items) - 1
                or all(_UNSTABLE_ITEM.fullmatch(later) is not None for later in items[item_index + 1 :])
            ):
                return timestamp.group("column")
    return None


def _docstring_nodes(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for owner in walk(tree):
        if not isinstance(owner, owners) or not owner.body:
            continue
        first = owner.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            found.add(id(first.value))
    return found


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
