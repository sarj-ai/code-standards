"""SARJ036 — Raw SQL INSERT executed in a test body — seed through the store.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_raw_sql_in_tests.py
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
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._sql import sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_EXECUTE_METHODS = frozenset({"execute", "executemany", "executescript", "fetch", "fetchrow", "fetchval"})
_TEXT_WRAPPER_NAMES = frozenset({"sa", "sqlalchemy"})

_INSERT_RE = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)


@final
class NoRawSqlInTests(Rule):
    id: str = "no-raw-sql-in-tests"
    code: str = "SARJ036"
    documentation = RuleDocumentation(
        summary="Tests should seed records through store or service methods instead of raw SQL inserts.",
        rationale="Raw inserts bypass the validation, defaults, events, and invariants exercised by production writes.",
        remediation="Create test records through the owning store or service API.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only literal `INSERT INTO` statements passed to known execution methods in test files are reported.",
            "Fixtures in `conftest.py`, migrations, dynamic SQL, reads, updates, and cleanup statements are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="raw-insert-test-seed",
                title="Test seeds data with raw SQL",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_call_store.py",
                        'async def test_create(conn):\n    await conn.execute("INSERT INTO call (id) VALUES (1)")\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_call_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="store-api-test-seed",
                title="Test seeds data through the store API",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_call_store.py",
                        "async def test_create(store):\n    await store.insert(make_call())\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_call_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or path.name == "conftest.py" or "migrations" in path.parts:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.Call):
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in _EXECUTE_METHODS) or not node.args:
                continue
            method = func.attr
            literal = _literal_text(_unwrap_text_call(node.args[0]))
            if literal is None or not _INSERT_RE.search(strip_sql_noise(literal)):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"raw SQL INSERT in `.{method}(...)` inside a test — "
                        "seed through the store/service method so the test "
                        "exercises the real write path."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _unwrap_text_call(node: ast.expr) -> ast.expr:
    """Unwrap a single-argument `text(...)` / `sa.text(...)` / `sqlalchemy.text(...)`."""
    match node:
        case ast.Call(func=func, args=[inner], keywords=[]):
            match func:
                case ast.Name(id="text"):
                    return inner
                case ast.Attribute(attr="text", value=ast.Name(id=recv)) if recv in _TEXT_WRAPPER_NAMES:
                    return inner
                case _:
                    return node
        case _:
            return node


def _literal_text(node: ast.expr) -> str | None:
    """Extract the literal text of a string argument, f-strings included."""
    direct = sql_string_value(node)
    if direct is not None:
        return direct
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append(" ")
    return "".join(parts)
