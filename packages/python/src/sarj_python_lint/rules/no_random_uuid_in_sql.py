from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_RANDOM_UUID_RE = re.compile(r"\b(?:gen_random_uuid|uuid_generate_v4)\s*\(", re.IGNORECASE)

# Require SQL structure so prose that merely names the function stays valid.
_SQL_SHAPE_RE = re.compile(
    r"\b(?:CREATE|ALTER|INSERT|UPDATE|SELECT|DEFAULT|VALUES)\b",
    re.IGNORECASE,
)

_UUIDV7_FUNCTION_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
    r"(?:uuid_?(?:generate_)?v7|uuid7)\s*\(",
    re.IGNORECASE,
)

_UUIDV7_BUILDERS = frozenset({"encode", "get_byte", "int8send", "overlay", "set_byte", "substring", "uuid_send"})

_MESSAGE = (
    "Random UUIDv4 generation in SQL — use `uuidv7()` (Postgres 18) "
    "so keys are time-ordered and inserts append to the index's right edge "
    "instead of scattering across every leaf page."
)


@final
class NoRandomUuidInSql(Rule):
    id: str = "no-random-uuid-in-sql"
    code: str = "SARJ053"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Embedded SQL generates a random UUIDv4 instead of a time-ordered UUIDv7.",
        rationale="Random UUIDv4 primary keys scatter inserts across B-tree pages; UUIDv7 keys preserve time ordering.",
        remediation="Use uuidv7() where the supported PostgreSQL version provides it.",
        category=RuleCategory.PERFORMANCE,
        aliases=("no-gen-random-uuid-in-sql",),
        limitations=(
            "Detection covers SQL-shaped Python string literals after masking SQL comments and quoted values.",
            "PostgreSQL gen_random_uuid() and uuid-ossp uuid_generate_v4() are covered.",
            "Known UUIDv7 compatibility functions and calls nested inside UUIDv7 bit-building helpers are excluded per occurrence.",
        ),
        examples=(
            RuleExample(
                example_id="random-uuid-default",
                title="Table defaults to a random UUID",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        'SQL = "CREATE TABLE call (id UUID PRIMARY KEY DEFAULT gen_random_uuid())"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="uuidv7-default",
                title="Table defaults to UUIDv7",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        'SQL = "CREATE TABLE call (id UUID PRIMARY KEY DEFAULT uuidv7())"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
            )
            for node in nodes(tree, ast.Constant)
            if isinstance(node.value, str) and _is_offending_sql(node.value)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_offending_sql(value: str) -> bool:
    masked = strip_sql_noise(value)
    matches = tuple(_RANDOM_UUID_RE.finditer(masked))
    if not matches or not _SQL_SHAPE_RE.search(masked):
        return False
    if _UUIDV7_FUNCTION_RE.search(masked):
        return False
    return any(not _inside_uuidv7_builder(masked, match.start()) for match in matches)


def _inside_uuidv7_builder(sql: str, position: int) -> bool:
    calls: list[str | None] = []
    index = 0
    while index < position:
        if sql[index].isalpha() or sql[index] == "_":
            end = index + 1
            while end < position and (sql[end].isalnum() or sql[end] == "_"):
                end += 1
            after = end
            while after < position and sql[after].isspace():
                after += 1
            if after < position and sql[after] == "(":
                calls.append(sql[index:end].lower())
                index = after + 1
                continue
            index = end
            continue
        if sql[index] == "(":
            calls.append(None)
        elif sql[index] == ")" and calls:
            calls.pop()
        index += 1
    return any(call in _UUIDV7_BUILDERS for call in calls)
