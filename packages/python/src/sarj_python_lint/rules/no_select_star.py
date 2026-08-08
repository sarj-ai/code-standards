"""SARJ021 — No `SELECT *` in a store query — list the columns you need.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_select_star.py
"""

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
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


# A real SQL query shape, so prose strings with the bare word "from" aren't matched.
_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_SELECT_KW = re.compile(r"\bSELECT\b", re.IGNORECASE)
_FROM_KW = re.compile(r"FROM\b", re.IGNORECASE)
_EXISTS_BEFORE = re.compile(r"\bEXISTS\s*\(\s*$", re.IGNORECASE)
# A `word.` immediately preceding a `*` marks a qualified star (`c.*`, `public.call.*`).
_QUALIFIED_PREFIX = re.compile(r"\w\.$")


def _has_real_select_star(sql: str) -> bool:
    selects = [m.start() for m in _SELECT_KW.finditer(sql)]
    for pos, ch in enumerate(sql):
        if ch != "*" or not _is_projection_star(sql, pos):
            continue
        owning = max((s for s in selects if s < pos), default=None)
        if owning is not None and _EXISTS_BEFORE.search(sql[:owning]) is None:
            return True
    return False


def _is_projection_star(sql: str, pos: int) -> bool:
    """Report whether the `*` at `pos` is a column-projection star."""
    if _QUALIFIED_PREFIX.search(sql[:pos]) is not None:
        return True
    before = pos - 1
    while before >= 0 and sql[before].isspace():
        before -= 1
    after = pos + 1
    while after < len(sql) and sql[after].isspace():
        after += 1
    before_char = sql[before] if before >= 0 else ""
    after_char = sql[after] if after < len(sql) else ""
    terminates = after_char in {"", ",", ")"} or _FROM_KW.match(sql, after) is not None
    if not terminates:
        return False
    return not (before_char == "(" and after_char == ")")


@final
class NoSelectStar(Rule):
    id: str = "no-select-star"
    code: str = "SARJ021"
    documentation = RuleDocumentation(
        summary="Store queries should select explicit columns instead of `*`.",
        rationale="Wildcard projections over-fetch data and can silently change row shapes when the schema evolves.",
        remediation="List every column consumed by the store result mapping.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only SQL string literals in recognized store modules are analyzed.",
            "The rule cannot infer the intended projection for an automatic fix.",
        ),
        examples=(
            RuleExample(
                example_id="wildcard-store-projection",
                title="Store query selects every column",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/call_store.py", 'QUERY = "SELECT * FROM call"\n'),),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-store-projection",
                title="Store query selects named columns",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/call_store.py", 'QUERY = "SELECT id, status FROM call"\n'),),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed:
                continue
            text = sql_string_value(node)
            if text is None:
                continue
            consumed.update(id(sub) for sub in walk(node))

            sql = strip_sql_noise(text)
            if _QUERY_SHAPE.search(sql) is None or not _has_real_select_star(sql):
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Store query uses SELECT * — list the columns explicitly "
                        "(* over-fetches and breaks class_row mapping). Suppress "
                        "with `# sarj-noqa: SARJ021`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
