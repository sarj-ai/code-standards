from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
from itertools import chain
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    is_generated_migration,
    is_postgres,
    mask_sql,
    mask_sql_literals_and_comments,
    redirect_to_model,
    source_location,
)


if TYPE_CHECKING:
    from pathlib import Path


PATTERN = re.compile(
    r'(?P<type>\b(?:VARCHAR|CHARACTER\s+VARYING))"?\s*\(',
    re.IGNORECASE,
)


@lru_cache(maxsize=8)
def _non_type_name_spans(source: str) -> tuple[tuple[int, int], ...] | None:
    try:
        statements = [statement for statement in parse_postgres(source) if statement is not None]
    except SqlglotError, RecursionError:
        return None
    if any(statement.find(exp.Command) is not None for statement in statements):
        return None
    spans: list[tuple[int, int]] = []
    for node in chain.from_iterable(statement.walk() for statement in statements):
        if not isinstance(node, (exp.Identifier, exp.Anonymous)):
            continue
        if isinstance(node, exp.Identifier) and _catalog_varchar(node.find_ancestor(exp.DataType)):
            continue
        start, end = node.meta.get("start"), node.meta.get("end")
        if isinstance(start, int) and isinstance(end, int):
            spans.append((start, end + 1))
    return tuple(sorted(spans))


def _catalog_varchar(datatype: exp.DataType | None) -> bool:
    kind = None if datatype is None else datatype.args.get("kind")
    if not isinstance(kind, exp.Dot):
        return False
    namespace, name = kind.left, kind.right
    if not isinstance(namespace, exp.Identifier) or not isinstance(name, exp.Identifier):
        return False
    namespace_name = namespace.name if namespace.quoted else namespace.name.lower()
    type_name = name.name if name.quoted else name.name.lower()
    return namespace_name == "pg_catalog" and type_name == "varchar"


@final
class PreferTextOverVarchar(Rule):
    id = "prefer-text-over-varchar"
    code = "SARJ104"
    documentation = RuleDocumentation(
        summary="VARCHAR(n) — use TEXT (+ CHECK length if needed).",
        rationale="PostgreSQL gives VARCHAR(n) no storage or performance advantage, while its length cap obscures a business constraint.",
        remediation="Use TEXT and express a real maximum length with an explicit CHECK constraint when needed.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "MySQL and SQLite sources are excluded because their VARCHAR behavior differs.",
            "Complete parseable PostgreSQL statements distinguish bounded builtin types from function names and custom schema types, including exact lower-case quoted varchar and pg_catalog qualification. Fragments and unsupported procedural syntax retain unquoted lexical detection.",
        ),
        examples=(
            RuleExample(
                example_id="bounded-varchar-column",
                title="Length-limited VARCHAR column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql("migrations/001_users.sql", "CREATE TABLE users (name VARCHAR(255) NOT NULL);\n"),
                ),
                focus_path=PurePosixPath("migrations/001_users.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="text-with-length-check",
                title="Text column with an explicit length constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_users.sql",
                        "CREATE TABLE users (name TEXT NOT NULL CHECK (char_length(name) <= 255));\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_users.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="quoted-builtin-varchar",
                title="A quoted builtin still declares a bounded VARCHAR column",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001_users.sql", 'CREATE TABLE users (name "varchar"(255));\n'),),
                focus_path=PurePosixPath("migrations/001_users.sql"),
                expected_count=1,
                public=True,
                scenario="type-name-ownership",
            ),
            RuleExample(
                example_id="qualified-function-varchar",
                title="A schema-qualified function keeps its own contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.sql("queries/name.sql", "SELECT app.varchar(255);\n"),),
                focus_path=PurePosixPath("queries/name.sql"),
                expected_count=0,
                public=True,
                scenario="type-name-ownership",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)
        if not is_postgres(source):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql_literals_and_comments(source, mask_dollar_literals=True)
        candidates = tuple(PATTERN.finditer(masked))
        non_types = _non_type_name_spans(source) if candidates else None
        starts = tuple(first for first, _ in non_types) if non_types is not None else ()
        code = mask_sql(source, mask_dollar_literals=True)
        for match in candidates:
            start = match.start("type")
            if not code[start].strip() and (
                non_types is None or source[start - 1 : match.end("type") + 1] != '"varchar"'
            ):
                continue
            preceding = bisect_right(starts, start) - 1
            if non_types is not None and preceding >= 0 and start < non_types[preceding][1]:
                continue
            location = source_location(source, start)
            diags.append(
                Diagnostic(
                    path=path,
                    line=location.line,
                    col=location.column,
                    code=self.code,
                    message=(
                        "Use TEXT (+ CHECK length if needed) — VARCHAR(n) has "
                        "no benefit in Postgres and hides a business rule in DDL."
                    ),
                )
            )
        return redirect_to_model(diags, model_owned=model_owned)
