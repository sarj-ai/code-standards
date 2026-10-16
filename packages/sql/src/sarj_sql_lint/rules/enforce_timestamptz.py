from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
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
    is_postgres_source,
    mask_sql,
    mask_sql_literals_and_comments,
    redirect_to_model,
    source_location,
)


if TYPE_CHECKING:
    from pathlib import Path


# Match TIMESTAMP unless followed by WITH TIME ZONE, allowing an optional (n) precision modifier.
PATTERN = re.compile(
    r"\bTIMESTAMP\b(?!\s*(?:\(\s*\d+\s*\)\s*)?WITH\s+TIME\s+ZONE\b)",
    re.IGNORECASE,
)

_OPENS_LIST_ITEM = frozenset("(,")
_CLOSES_LIST_ITEM = frozenset(",)")


def _is_column_reference(source: str, start: int, end: int) -> bool:
    before = start - 1
    while before >= 0 and source[before].isspace():
        before -= 1
    after = end
    while after < len(source) and source[after].isspace():
        after += 1
    return (
        before >= 0
        and source[before] in _OPENS_LIST_ITEM
        and after < len(source)
        and source[after] in _CLOSES_LIST_ITEM
    )


@lru_cache(maxsize=8)
def _identifier_spans(source: str) -> tuple[tuple[int, int], ...] | None:
    try:
        statements = parse_postgres(source)
    except SqlglotError, RecursionError:
        # Fragments and unsupported procedural syntax retain lexical checks.
        return None
    if any(statement is not None and statement.find(exp.Command) is not None for statement in statements):
        return None
    return tuple(
        sorted(
            span
            for statement in statements
            if statement is not None
            for identifier in statement.find_all(exp.Identifier)
            if (span := _reference_span(identifier)) is not None
        )
    )


def _reference_span(identifier: exp.Identifier) -> tuple[int, int] | None:
    datatype = identifier.find_ancestor(exp.DataType)
    if datatype is not None and _catalog_timestamp(datatype):
        return None
    start = identifier.meta.get("start")
    end = identifier.meta.get("end")
    if isinstance(start, int) and isinstance(end, int):
        return start, end + 1
    return None


def _catalog_timestamp(datatype: exp.DataType) -> bool:
    kind = datatype.args.get("kind")
    if not isinstance(kind, exp.Dot):
        return False
    namespace, name = kind.left, kind.right
    if not isinstance(namespace, exp.Identifier) or not isinstance(name, exp.Identifier):
        return False
    namespace_name = namespace.name if namespace.quoted else namespace.name.lower()
    type_name = name.name if name.quoted else name.name.lower()
    return namespace_name == "pg_catalog" and type_name == "timestamp"


@final
class EnforceTimestamptz(Rule):
    id = "enforce-timestamptz"
    code = "SARJ101"
    documentation = RuleDocumentation(
        summary="TIMESTAMP without TIME ZONE — use TIMESTAMPTZ.",
        rationale="Naive timestamps discard offset context and make cross-time-zone comparisons ambiguous.",
        remediation="Declare persisted instants as TIMESTAMPTZ or TIMESTAMP WITH TIME ZONE.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Complete parseable PostgreSQL statements distinguish identifier positions from type keywords, including exact lower-case quoted built-ins and pg_catalog qualification. Custom schemas and quoted mixed-case type names are not inferred. Fragments and unsupported procedural syntax retain unquoted lexical detection.",
        ),
        examples=(
            RuleExample(
                example_id="naive-created-at",
                title="Naive timestamp column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_orders.sql",
                        "CREATE TABLE orders (created_at TIMESTAMP NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_orders.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="timestamp-column-reference",
                title="A column identifier does not declare a naive type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.sql("supabase/queries/events.sql", "SELECT timestamp FROM events;\n"),),
                focus_path=PurePosixPath("supabase/queries/events.sql"),
                expected_count=0,
                scenario="identifier-type",
                public=True,
            ),
            RuleExample(
                example_id="timestamp-column-and-naive-cast",
                title="A column identifier does not hide a naive cast",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("supabase/queries/events.sql", "SELECT timestamp::TIMESTAMP FROM events;\n"),),
                focus_path=PurePosixPath("supabase/queries/events.sql"),
                expected_count=1,
                scenario="identifier-type",
                public=True,
            ),
            RuleExample(
                example_id="zoned-created-at",
                title="Timestamp with time-zone semantics",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_orders.sql",
                        "CREATE TABLE orders (created_at TIMESTAMPTZ NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_orders.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )

    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_source(path, source):
            return []
        model_owned = is_generated_migration(path, source)

        diags: list[Diagnostic] = []
        masked = mask_sql_literals_and_comments(source, mask_dollar_literals=True)
        candidates = tuple(PATTERN.finditer(masked))
        identifiers = _identifier_spans(source) if candidates else None
        starts = tuple(first for first, _ in identifiers) if identifiers is not None else ()
        code = mask_sql(source, mask_dollar_literals=True)
        for match in candidates:
            start = match.start()
            if not code[start].strip() and (
                identifiers is None or source[start - 1 : match.end() + 1] != '"timestamp"'
            ):
                continue
            preceding = bisect_right(starts, start) - 1
            if (identifiers is not None and preceding >= 0 and start < identifiers[preceding][1]) or (
                _is_column_reference(masked, start, match.end())
            ):
                continue
            location = source_location(source, start)
            diags.append(
                Diagnostic(
                    path=path,
                    line=location.line,
                    col=location.column,
                    code=self.code,
                    message=(
                        "Use `TIMESTAMPTZ` (or `TIMESTAMP WITH TIME ZONE`) — "
                        "naive TIMESTAMP discards offset and is rarely correct."
                    ),
                )
            )
        return redirect_to_model(diags, model_owned=model_owned)
