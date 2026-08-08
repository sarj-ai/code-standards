"""SARJ025 — No `OFFSET` pagination in a store query — use a keyset cursor.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_offset_pagination.py
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


# Require a shared dialect parameter after `OFFSET`, excluding prose and
# BigQuery's `WITH OFFSET AS` array indexing.
_OFFSET_PAGINATION = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|(?:0*[1-9]\d*))",
    re.IGNORECASE,
)


@final
class NoOffsetPagination(Rule):
    id: str = "no-offset-pagination"
    code: str = "SARJ025"
    documentation = RuleDocumentation(
        summary="Store queries should use keyset cursors instead of `OFFSET` pagination.",
        rationale="Large offsets require scanning discarded rows and can skip or repeat results during concurrent writes.",
        remediation="Filter on the ordered key after the last result, then apply `ORDER BY` and `LIMIT`.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only SQL string literals in recognized store modules are analyzed.",
            "Dynamic SQL, comments, prose, and BigQuery `WITH OFFSET AS` array indexing are excluded.",
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
                title="Page selected after the last ordered key",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'QUERY = "SELECT id FROM task WHERE id > :cursor ORDER BY id LIMIT :limit"\n',
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
            if _OFFSET_PAGINATION.search(sql) is None:
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Store query uses OFFSET pagination (O(N), unstable under "
                        "concurrent writes) — use a keyset cursor (WHERE id > :cursor "
                        "ORDER BY id LIMIT n). Suppress with `# sarj-noqa: SARJ025`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
